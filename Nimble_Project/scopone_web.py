#!/usr/bin/env python3
"""
Scopone Scientifico - Web UI interattiva
Apri http://localhost:5000 nel browser. Clicca sulle tue carte per giocare.
I turni degli AI sono mostrati con un ritardo di 5 secondi.
"""

import random
import time
from queue import Queue, Empty
from threading import Thread

from flask import Flask, render_template
from flask_socketio import SocketIO, emit

# Import game logic from scopone
from scopone import (
    Carta, crea_mazzo, distribuisci, quale_squadra,
    catture_valide, turno_ai, risolvi_giocata,
    calcola_carte, calcola_ori, calcola_settebello, calcola_primiera, calcola_napula_squadre,
    GIOCATORI, NOMI_VALORI, SUD_IDX,
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
                punteggio_ns, punteggio_eo, current_player, message, mano_sud_idx=None):
    """Costruisce lo stato JSON per il frontend."""
    mani_serialized = []
    for i, mano in enumerate(mani):
        if i == SUD_IDX:
            mani_serialized.append([carta_to_dict(c) for c in mano])
        else:
            # Altri giocatori: mostra solo numero di carte
            mani_serialized.append({"count": len(mano)})
    return {
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


def run_game_loop():
    """Loop principale del gioco, eseguito in un thread separato."""
    punteggio_ns = 0
    punteggio_eo = 0
    mano_num = 1

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

        socketio.emit("hand_start", {"mano_num": mano_num, "punteggio_ns": punteggio_ns, "punteggio_eo": punteggio_eo})

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
                f"Turno di {giocatore}"
            ))

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
                carta, cattura = turno_ai(mano, tavolo, ultima_mano=ultima_giocata_mano)

            socketio.emit("play", {
                "player": giocatore,
                "card": carta_to_dict(carta),
                "capture": [carta_to_dict(c) for c in cattura] if cattura else None,
                "scopa": bool(cattura and len(cattura) == len(tavolo) and not ultima_giocata_mano),
            })

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

        pt_carte_ns, pt_carte_eo = calcola_carte(prese_ns, prese_eo)
        pt_ori_ns, pt_ori_eo = calcola_ori(prese_ns, prese_eo)
        pt_sb_ns, pt_sb_eo = calcola_settebello(prese_ns, prese_eo)
        pt_prim_ns, pt_prim_eo = calcola_primiera(prese_ns, prese_eo)
        pt_nap_ns, pt_nap_eo = calcola_napula_squadre(prese_ns, prese_eo)
        pt_mano_ns = pt_carte_ns + pt_ori_ns + pt_sb_ns + pt_prim_ns + scope_ns + pt_nap_ns
        pt_mano_eo = pt_carte_eo + pt_ori_eo + pt_sb_eo + pt_prim_eo + scope_eo + pt_nap_eo
        punteggio_ns += pt_mano_ns
        punteggio_eo += pt_mano_eo

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

        if punteggio_ns >= 21 or punteggio_eo >= 21:
            winner = "NS" if punteggio_ns > punteggio_eo else ("EO" if punteggio_eo > punteggio_ns else "Pareggio")
            socketio.emit("game_over", {"winner": winner, "punteggio_ns": punteggio_ns, "punteggio_eo": punteggio_eo})
            break
        mano_num += 1
        time.sleep(2)  # Pausa prima della prossima mano


@socketio.on("connect")
def handle_connect():
    emit("connected", {"message": "Connesso. La partita inizia quando sei pronto."})


@socketio.on("start_game")
def handle_start():
    emit("state", {"message": "Avvio partita..."})
    Thread(target=run_game_loop, daemon=True).start()


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
    print("\n*** SCOPONE SCIENTIFICO - Web UI ***")
    print("Apri http://localhost:5000 nel browser")
    print("Clicca su 'Avvia partita' per iniziare\n")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
