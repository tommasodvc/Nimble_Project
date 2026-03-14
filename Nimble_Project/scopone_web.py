#!/usr/bin/env python3
"""
Scopone Scientifico - Web UI interattiva
Apri http://localhost:5000 nel browser. Clicca sulle tue carte per giocare.
I turni degli AI sono mostrati con un ritardo di 5 secondi.
"""
from dotenv import load_dotenv
load_dotenv()

import random
import time
from queue import Queue, Empty
from threading import Thread

from flask import Flask, render_template
from flask_socketio import SocketIO, emit

# Import game logic from scopone
from scopone import (
    Carta, crea_mazzo, distribuisci, quale_squadra,
    catture_valide, risolvi_giocata,
    turno_ai_easy, turno_ai_medium, turno_ai_hard,
    calcola_carte, calcola_ori, calcola_settebello, calcola_primiera, calcola_napula_squadre,
    GIOCATORI, NOMI_VALORI, SUD_IDX, SEMI, VALORI_PREMIERA,
)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "scopone-secret"
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

AI_DELAY_SEC = 5
human_input_queue: Queue = Queue()


def carta_to_dict(c: Carta) -> dict:
    return {"seme": c.seme, "valore": c.valore}


def dict_to_carta(d: dict) -> Carta:
    return Carta(d["seme"], d["valore"])


def build_state(tavolo, mani, prese_ns, prese_eo, scope_ns, scope_eo,
                punteggio_ns, punteggio_eo, current_player, message,
                carte_scoperte: bool = False,
                play_history: list | None = None):
    """Costruisce lo stato JSON per il frontend."""
    mani_serialized = []
    for i, mano in enumerate(mani):
        if i == SUD_IDX or carte_scoperte:
            mani_serialized.append([carta_to_dict(c) for c in mano])
        else:
            mani_serialized.append({"count": len(mano)})
    out = {
        "tavolo": [carta_to_dict(c) for c in tavolo],
        "mani": mani_serialized,
        "prese_ns": len(prese_ns),
        "prese_eo": len(prese_eo),
        "scope_ns": scope_ns,
        "scope_eo": scope_eo,
        "punteggio_ns": punteggio_ns,
        "punteggio_eo": punteggio_eo,
        "current_player": current_player,
        "message": message,
        "is_your_turn": current_player == "Sud",
    }
    if carte_scoperte and play_history:
        out["play_history"] = play_history
    return out


def _primiera_detail(prese: list) -> dict:
    """Dettaglio primiera: per ogni seme il miglior valore."""
    detail = {}
    for seme in SEMI:
        carte = [c for c in prese if c.seme == seme]
        if carte:
            best = max(carte, key=lambda c: c.valore_primiera)
            detail[seme] = {"valore": best.valore, "punti": VALORI_PREMIERA.get(best.valore, 10)}
    return detail


def _ai_move(level: str, mano, tavolo, ultima_mano, prese_ns, prese_eo, carte_giocate, giocatore):
    if level == "easy":
        return turno_ai_easy(mano, tavolo, ultima_mano)
    if level == "hard":
        return turno_ai_hard(mano, tavolo, ultima_mano, prese_ns, prese_eo, carte_giocate, giocatore)
    return turno_ai_medium(mano, tavolo, ultima_mano, prese_ns, prese_eo, carte_giocate)


def run_game_loop(target_points: int = 21, ai_levels: dict | None = None, carte_scoperte: bool = False):
    """Loop principale del gioco, eseguito in un thread separato."""
    punteggio_ns = 0
    punteggio_eo = 0
    mano_num = 1
    total_prese_ns: list = []
    total_prese_eo: list = []
    total_scope_ns = 0
    total_scope_eo = 0
    total_pt_carte_ns = total_pt_carte_eo = 0
    total_pt_ori_ns = total_pt_ori_eo = 0
    total_pt_sb_ns = total_pt_sb_eo = 0
    total_pt_prim_ns = total_pt_prim_eo = 0
    total_pt_nap_ns = total_pt_nap_eo = 0
    ai_levels = ai_levels or {g: "medium" for g in ("Est", "Nord", "Ovest")}

    while True:
        mazzo = crea_mazzo()
        mani = distribuisci(mazzo)
        tavolo = []
        prese_ns = []
        prese_eo = []
        scope_ns = 0
        scope_eo = 0
        ultimo_catturante = None
        giocatore_idx = 0
        carte_giocate = 0
        totale_giocate = 40
        play_history: list = []

        socketio.emit("hand_start", {
            "mano_num": mano_num, "punteggio_ns": punteggio_ns, "punteggio_eo": punteggio_eo,
            "ai_levels": ai_levels, "carte_scoperte": carte_scoperte,
        })

        while any(mani):
            giocatore = GIOCATORI[giocatore_idx]
            mano = mani[giocatore_idx]
            if not mano:
                giocatore_idx = (giocatore_idx + 1) % 4
                continue

            ultima_giocata_mano = carte_giocate == totale_giocate - 1

            socketio.emit("state", build_state(
                tavolo, mani, prese_ns, prese_eo, scope_ns, scope_eo,
                punteggio_ns, punteggio_eo, giocatore,
                f"Turno di {giocatore}",
                carte_scoperte=carte_scoperte,
                play_history=play_history,
            ))

            spiegazione = None
            if giocatore == "Sud":
                # Aspetta scelta carta dall'umano
                try:
                    payload = human_input_queue.get(timeout=300)
                    idx = payload.get("card_index", 0)
                    carta = mano[min(idx, len(mano) - 1)]
                except Empty:
                    carta = random.choice(mano)
                opzioni = catture_valide(carta, tavolo)
                if not opzioni:
                    cattura = None
                elif len(opzioni) == 1:
                    cattura = opzioni[0]
                else:
                    # Più opzioni: chiedi al frontend quale cattura scegliere
                    socketio.emit("choose_capture", {
                        "card": carta_to_dict(carta),
                        "options": [[carta_to_dict(c) for c in opt] for opt in opzioni]
                    })
                    try:
                        payload2 = human_input_queue.get(timeout=60)
                        capture_idx = payload2.get("capture_index", 0)
                        cattura = opzioni[min(capture_idx, len(opzioni) - 1)]
                    except Empty:
                        cattura = opzioni[0]
            else:
                # Turno AI: ritardo 5 secondi poi gioca
                time.sleep(AI_DELAY_SEC)
                level = ai_levels.get(giocatore, "medium")
                res = _ai_move(
                    level, mano, tavolo, ultima_giocata_mano,
                    prese_ns, prese_eo, carte_giocate, giocatore,
                )
                carta, cattura = res[0], res[1]
                if len(res) >= 3:
                    spiegazione = res[2]

            play_payload = {
                "player": giocatore,
                "card": carta_to_dict(carta),
                "capture": [carta_to_dict(c) for c in cattura] if cattura else None,
                "scopa": bool(cattura and len(cattura) == len(tavolo) and not ultima_giocata_mano),
            }
            if spiegazione:
                play_payload["spiegazione"] = spiegazione
            socketio.emit("play", play_payload)

            play_history.append({"giocatore": giocatore, "seme": carta.seme, "valore": carta.valore})
            mano.remove(carta)
            tavolo, prese_ns, prese_eo, scope_ns, scope_eo, _ = risolvi_giocata(
                carta, cattura, tavolo, prese_ns, prese_eo,
                scope_ns, scope_eo, giocatore, ultima_giocata_mano
            )
            if cattura:
                ultimo_catturante = giocatore

            carte_giocate += 1
            giocatore_idx = (giocatore_idx + 1) % 4

        if tavolo and ultimo_catturante:
            squadra = quale_squadra(ultimo_catturante)
            if "Nord" in squadra or "Sud" in squadra:
                prese_ns.extend(tavolo)
            else:
                prese_eo.extend(tavolo)

        total_prese_ns.extend(prese_ns)
        total_prese_eo.extend(prese_eo)
        total_scope_ns += scope_ns
        total_scope_eo += scope_eo

        pt_carte_ns, pt_carte_eo = calcola_carte(prese_ns, prese_eo)
        pt_ori_ns, pt_ori_eo = calcola_ori(prese_ns, prese_eo)
        pt_sb_ns, pt_sb_eo = calcola_settebello(prese_ns, prese_eo)
        pt_prim_ns, pt_prim_eo = calcola_primiera(prese_ns, prese_eo)
        pt_nap_ns, pt_nap_eo = calcola_napula_squadre(prese_ns, prese_eo)
        pt_mano_ns = pt_carte_ns + pt_ori_ns + pt_sb_ns + pt_prim_ns + scope_ns + pt_nap_ns
        pt_mano_eo = pt_carte_eo + pt_ori_eo + pt_sb_eo + pt_prim_eo + scope_eo + pt_nap_eo
        punteggio_ns += pt_mano_ns
        punteggio_eo += pt_mano_eo
        total_pt_carte_ns += pt_carte_ns
        total_pt_carte_eo += pt_carte_eo
        total_pt_ori_ns += pt_ori_ns
        total_pt_ori_eo += pt_ori_eo
        total_pt_sb_ns += pt_sb_ns
        total_pt_sb_eo += pt_sb_eo
        total_pt_prim_ns += pt_prim_ns
        total_pt_prim_eo += pt_prim_eo
        total_pt_nap_ns += pt_nap_ns
        total_pt_nap_eo += pt_nap_eo

        socketio.emit("hand_over", {
            "pt_carte_ns": pt_carte_ns, "pt_carte_eo": pt_carte_eo,
            "pt_ori_ns": pt_ori_ns, "pt_ori_eo": pt_ori_eo,
            "pt_sb_ns": pt_sb_ns, "pt_sb_eo": pt_sb_eo,
            "pt_prim_ns": pt_prim_ns, "pt_prim_eo": pt_prim_eo,
            "scope_ns": scope_ns, "scope_eo": scope_eo,
            "pt_nap_ns": pt_nap_ns, "pt_nap_eo": pt_nap_eo,
            "pt_mano_ns": pt_mano_ns, "pt_mano_eo": pt_mano_eo,
            "punteggio_ns": punteggio_ns, "punteggio_eo": punteggio_eo,
        })

        if punteggio_ns >= target_points or punteggio_eo >= target_points:
            winner = "NS" if punteggio_ns > punteggio_eo else ("EO" if punteggio_eo > punteggio_ns else "Pareggio")
            ori_ns_tot = sum(1 for c in total_prese_ns if c.seme == "Ori")
            ori_eo_tot = sum(1 for c in total_prese_eo if c.seme == "Ori")
            prim1 = _primiera_detail(total_prese_ns)
            prim2 = _primiera_detail(total_prese_eo)
            recap = {
                "winner": winner,
                "punteggio_ns": punteggio_ns,
                "punteggio_eo": punteggio_eo,
                "team1_cards": [carta_to_dict(c) for c in prese_ns],
                "team2_cards": [carta_to_dict(c) for c in prese_eo],
                "breakdown": {
                    "team1": {
                        "carte": {"count": len(total_prese_ns), "pt": total_pt_carte_ns},
                        "ori": {"count": ori_ns_tot, "pt": total_pt_ori_ns},
                        "settebello": total_pt_sb_ns,
                        "primiera": {"detail": prim1, "pt": total_pt_prim_ns},
                        "scope": total_scope_ns,
                        "napula": total_pt_nap_ns,
                    },
                    "team2": {
                        "carte": {"count": len(total_prese_eo), "pt": total_pt_carte_eo},
                        "ori": {"count": ori_eo_tot, "pt": total_pt_ori_eo},
                        "settebello": total_pt_sb_eo,
                        "primiera": {"detail": prim2, "pt": total_pt_prim_eo},
                        "scope": total_scope_eo,
                        "napula": total_pt_nap_eo,
                    },
                },
            }
            socketio.emit("game_over", recap)
            break
        mano_num += 1
        time.sleep(2)  # Pausa prima della prossima mano


@socketio.on("connect")
def handle_connect():
    emit("connected", {"message": "Connesso. La partita inizia quando sei pronto."})


@socketio.on("start_game")
def handle_start(data=None):
    target = 21
    ai_levels = {"Est": "medium", "Nord": "medium", "Ovest": "medium"}
    if data:
        if "target_points" in data:
            try:
                target = int(data["target_points"])
                if target < 1:
                    target = 1
                if target > 101:
                    target = 101
            except (ValueError, TypeError):
                pass
        if "ai_levels" in data and isinstance(data["ai_levels"], dict):
            ai_levels.update(data["ai_levels"])
        carte_scoperte = data.get("carte_scoperte", False)
    else:
        carte_scoperte = False
    emit("state", {"message": "Avvio partita..."})
    Thread(target=run_game_loop, kwargs={"target_points": target, "ai_levels": ai_levels, "carte_scoperte": carte_scoperte}, daemon=True).start()


@socketio.on("play_card")
def handle_play_card(data):
    human_input_queue.put({"card_index": data.get("card_index", 0)})


@socketio.on("capture_choice")
def handle_capture_choice(data):
    human_input_queue.put({"capture_index": data.get("capture_index", 0)})


@app.route("/")
def index():
    return render_template("scopone.html")


if __name__ == "__main__":
    PORT = 5001  # 5000 often in use by AirPlay on macOS
    print("\n*** SCOPONE SCIENTIFICO - Web UI ***")
    print(f"Apri http://localhost:{PORT} nel browser")
    print("Clicca su 'Avvia partita' per iniziare\n")
    socketio.run(app, host="0.0.0.0", port=PORT, debug=False)
