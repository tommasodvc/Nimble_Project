#!/usr/bin/env python3
"""
Scopone Scientifico - Implementazione locale single-player
Giocatore umano = Sud (S), in squadra con Nord (N) vs Est (E) e Ovest (O)
"""

import random
from itertools import combinations

try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# --- Costanti ---
SEMI = ["Ori", "Coppe", "Spade", "Bastoni"]
VALORI = list(range(1, 11))  # 1-7 numerici, 8=Fante, 9=Donna, 10=Re
NOMI_VALORI = {1: "Asso", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7",
               8: "Fante", 9: "Donna", 10: "Re"}

# Valori primiera: 7→21, 6→18, Asso→16, 5→15, 4→14, 3→13, 2→12, F/D/R→10
VALORI_PREMIERA = {
    7: 21, 6: 18, 1: 16, 5: 15, 4: 14, 3: 13, 2: 12,
    8: 10, 9: 10, 10: 10
}

GIOCATORI = ["Est", "Nord", "Ovest", "Sud"]
SUD_IDX = 3  # Sud è l'umano
SQUADRA_NS = {"Nord", "Sud"}
SQUADRA_EO = {"Est", "Ovest"}


# --- Strutture dati ---

class Carta:
    def __init__(self, seme: str, valore: int):
        self.seme = seme
        self.valore = valore
        self.valore_primiera = VALORI_PREMIERA.get(valore, 10)

    def __repr__(self):
        nome = NOMI_VALORI.get(self.valore, str(self.valore))
        return f"{nome} di {self.seme}"


def crea_mazzo() -> list[Carta]:
    """Crea e mescola un mazzo da 40 carte."""
    mazzo = []
    for seme in SEMI:
        for valore in VALORI:
            mazzo.append(Carta(seme, valore))
    random.shuffle(mazzo)
    return mazzo


def distribuisci(mazzo: list[Carta]) -> list[list[Carta]]:
    """Distribuisce 10 carte a ciascun giocatore. Ordine: Est, Nord, Ovest, Sud."""
    mani = [[], [], [], []]
    for i in range(40):
        mani[i % 4].append(mazzo[i])
    return mani


def quale_squadra(giocatore: str) -> set:
    if giocatore in SQUADRA_NS:
        return SQUADRA_NS
    return SQUADRA_EO


# --- Logica catture ---

def trova_match_diretto(carta_giocata: Carta, tavolo: list[Carta]) -> list[list[Carta]]:
    """Trova carte sul tavolo con lo stesso valore (match diretto = obbligatorio)."""
    return [[c] for c in tavolo if c.valore == carta_giocata.valore]


def trova_catture_somma(carta_giocata: Carta, tavolo: list[Carta]) -> list[list[Carta]]:
    """Trova tutti i sottoinsiemi di tavolo la cui somma dei valori = carta_giocata.valore."""
    obiettivo = carta_giocata.valore
    risultat = []
    for r in range(1, len(tavolo) + 1):
        for combo in combinations(tavolo, r):
            if sum(c.valore for c in combo) == obiettivo:
                risultat.append(list(combo))
    return risultat


def catture_valide(carta_giocata: Carta, tavolo: list[Carta]) -> list[list[Carta]]:
    """
    Restituisce le catture valide.
    Se esiste match diretto → SOLO match diretti (obbligatorio, somma vietata).
    Altrimenti → catture per somma.
    """
    match_diretti = trova_match_diretto(carta_giocata, tavolo)
    if match_diretti:
        return match_diretti
    return trova_catture_somma(carta_giocata, tavolo)


# --- Turno AI ---

def _valuta_throw(carta: Carta, tavolo: list[Carta]) -> float:
    """
    Quanto è bene gettare questa carta (più alto = meglio gettare).
    Preferisce: bassa primiera, non-Ori, carte che non creano facili catture.
    """
    score = 0.0
    # Tieni 7, 6, Asso (alta primiera); getta Fante, Donna, Re, 2-5
    score += 22 - carta.valore_primiera
    # Proteggi Ori (per Ori + Napula)
    if carta.seme != "Ori":
        score += 8
    # Penalizza se gettare crea match diretto per l'avversario
    valori_tavolo = {c.valore for c in tavolo}
    if carta.valore in valori_tavolo:
        score -= 4
    # Penalizza gettare valori alti che permettono catture multiple (7,6,Asso)
    if carta.valore in (7, 6, 1) and len(tavolo) >= 2:
        somma_tavolo = sum(c.valore for c in tavolo)
        if somma_tavolo + carta.valore in (10, 20, 30):
            score -= 6
    return score


def turno_ai_easy(
    mano: list[Carta],
    tavolo: list[Carta],
    ultima_mano: bool = False,
) -> tuple[Carta, list[Carta] | None]:
    """
    Easy: catture base (Scopa > Primiera > Ori), getti intelligenti.
    """
    mosse_con_cattura: list[tuple[Carta, list[Carta]]] = []
    for c in mano:
        for cattura in catture_valide(c, tavolo):
            mosse_con_cattura.append((c, cattura))

    if not mosse_con_cattura:
        best = max(mano, key=lambda c: _valuta_throw(c, tavolo))
        return best, None

    def valuta(c: Carta, cattura: list[Carta]) -> tuple[int, int, int]:
        scopa = 1 if (not ultima_mano and len(cattura) == len(tavolo)) else 0
        totale = [c] + cattura
        primiera = sum(x.valore_primiera for x in totale)
        ori = sum(1 for x in totale if x.seme == "Ori")
        return (scopa, primiera, ori)

    best = max(mosse_con_cattura, key=lambda m: valuta(m[0], m[1]))
    return best[0], best[1]


def turno_ai_medium(
    mano: list[Carta],
    tavolo: list[Carta],
    ultima_mano: bool = False,
    prese_ns: list | None = None,
    prese_eo: list | None = None,
    carte_giocate: int = 0,
) -> tuple[Carta, list[Carta] | None]:
    """
    Medium: come Easy + Napula, awareness fine mano, catture difensive.
    """
    prese_ns = prese_ns or []
    prese_eo = prese_eo or []
    mosse_con_cattura: list[tuple[Carta, list[Carta]]] = []
    for c in mano:
        for cattura in catture_valide(c, tavolo):
            mosse_con_cattura.append((c, cattura))

    if not mosse_con_cattura:
        best = max(mano, key=lambda c: _valuta_throw(c, tavolo))
        return best, None

    def valuta(c: Carta, cattura: list[Carta]) -> tuple[int, int, int, int]:
        scopa = 1 if (not ultima_mano and len(cattura) == len(tavolo)) else 0
        totale = [c] + cattura
        primiera = sum(x.valore_primiera for x in totale)
        ori = sum(1 for x in totale if x.seme == "Ori")
        napula_bonus = 0
        if ori >= 2:
            ori_vals = [x.valore for x in totale if x.seme == "Ori"]
            if 1 in ori_vals and 2 in ori_vals:
                napula_bonus = 2
            elif 1 in ori_vals or 7 in ori_vals:
                napula_bonus = 1
        carte_awareness = 1 if carte_giocate > 30 and (len(prese_ns) + len(prese_eo) + len(tavolo)) > 30 else 0
        return (scopa, primiera, ori + napula_bonus, carte_awareness)

    best = max(mosse_con_cattura, key=lambda m: valuta(m[0], m[1]))
    return best[0], best[1]


def turno_ai(mano, tavolo, ultima_mano=False, prese_ns=None, prese_eo=None, carte_giocate=0):
    """Alias per turno_ai_medium (compatibilità)."""
    return turno_ai_medium(mano, tavolo, ultima_mano, prese_ns, prese_eo, carte_giocate)


def _carta_repr(c: Carta) -> dict:
    return {"seme": c.seme, "valore": c.valore}


def turno_ai_hard(
    mano: list[Carta],
    tavolo: list[Carta],
    ultima_mano: bool = False,
    prese_ns: list | None = None,
    prese_eo: list | None = None,
    carte_giocate: int = 0,
    giocatore: str = "",
) -> tuple[Carta, list[Carta] | None]:
    """
    Hard: chiama LLM API (OpenAI) per la mossa. Fallback a medium se errore.
    """
    try:
        import os
        import json
        from openai import OpenAI
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        if not client.api_key:
            return turno_ai_medium(mano, tavolo, ultima_mano, prese_ns, prese_eo, carte_giocate)

        state = {
            "mano": [_carta_repr(c) for c in mano],
            "tavolo": [_carta_repr(c) for c in tavolo],
            "prese_ns": len(prese_ns or []),
            "prese_eo": len(prese_eo or []),
            "giocatore": giocatore,
        }
        prompt = f"""Sei un esperto di Scopone Scientifico. Stato: {json.dumps(state)}.
Regole: 1) Match diretto obbligatorio (stesso valore). 2) Senza match diretto, somma valori.
Devi giocare UNA carta da mano. Se può catturare, indica quali carte del tavolo (o null).
Rispondi SOLO con JSON: {{"carta": {{"seme":"...","valore":N}}, "cattura": [...] o null}}"""

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
        )
        text = resp.choices[0].message.content.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        data = json.loads(text)
        cd = data.get("carta", {})
        carta = next((c for c in mano if c.seme == cd.get("seme") and c.valore == cd.get("valore")), None)
        if not carta:
            return turno_ai_medium(mano, tavolo, ultima_mano, prese_ns, prese_eo, carte_giocate)
        opts = catture_valide(carta, tavolo)
        cattura = None
        if opts and data.get("cattura"):
            for opt in opts:
                if len(opt) == len(data["cattura"]) and all(
                    any(x.seme == d["seme"] and x.valore == d["valore"] for x in opt)
                    for d in data["cattura"]
                ):
                    cattura = opt
                    break
            if not cattura:
                cattura = opts[0]
        elif opts:
            cattura = opts[0]
        return carta, cattura
    except Exception:
        return turno_ai_medium(mano, tavolo, ultima_mano, prese_ns, prese_eo, carte_giocate)


# --- Risoluzione giocata ---

def risolvi_giocata(
    carta: Carta,
    cattura: list[Carta] | None,
    tavolo: list[Carta],
    prese_ns: list[Carta],
    prese_eo: list[Carta],
    scope_ns: int,
    scope_eo: int,
    giocatore: str,
    ultima_mano: bool,
) -> tuple[list[Carta], list[Carta], list[Carta], int, int, bool]:
    """
    Aggiorna tavolo, prese, scope. Ritorna (tavolo, prese_ns, prese_eo, scope_ns, scope_eo, scopa_fatta).
    """
    scopa_fatta = False

    if cattura:
        squadra = quale_squadra(giocatore)
        prese = prese_ns if "Nord" in squadra or "Sud" in squadra else prese_eo
        prese.append(carta)
        prese.extend(cattura)
        for c in cattura:
            tavolo.remove(c)

        if not tavolo and not ultima_mano:
            if "Nord" in squadra or "Sud" in squadra:
                scope_ns += 1
            else:
                scope_eo += 1
            scopa_fatta = True
            print("\n  *** SCOPA! ***\n")
    else:
        tavolo.append(carta)

    return tavolo, prese_ns, prese_eo, scope_ns, scope_eo, scopa_fatta


# --- Punteggio fine mano ---

def calcola_carte(prese_ns: list[Carta], prese_eo: list[Carta]) -> tuple[int, int]:
    """Carte: >20 carte = 1 pt. Pareggio = 0."""
    cn, ce = len(prese_ns), len(prese_eo)
    if cn > 20:
        return 1, 0
    if ce > 20:
        return 0, 1
    return 0, 0


def calcola_ori(prese_ns: list[Carta], prese_eo: list[Carta]) -> tuple[int, int]:
    """Ori: più carte Ori = 1 pt."""
    on = sum(1 for c in prese_ns if c.seme == "Ori")
    oe = sum(1 for c in prese_eo if c.seme == "Ori")
    if on > oe:
        return 1, 0
    if oe > on:
        return 0, 1
    return 0, 0


def ha_settebello(prese: list[Carta]) -> bool:
    return any(c.seme == "Ori" and c.valore == 7 for c in prese)


def calcola_settebello(prese_ns: list[Carta], prese_eo: list[Carta]) -> tuple[int, int]:
    """Settebello: 7 di Ori = 1 pt."""
    if ha_settebello(prese_ns):
        return 1, 0
    if ha_settebello(prese_eo):
        return 0, 1
    return 0, 0


def calcola_primiera(prese_ns: list[Carta], prese_eo: list[Carta]) -> tuple[int, int]:
    """Per ogni seme, max valore_primiera; somma 4 semi. Maggiore = 1 pt. Seme mancante = 0."""
    def punteggio_primiera(prese: list[Carta]) -> int:
        tot = 0
        for seme in SEMI:
            carte_seme = [c for c in prese if c.seme == seme]
            if carte_seme:
                tot += max(c.valore_primiera for c in carte_seme)
        return tot

    pn = punteggio_primiera(prese_ns)
    pe = punteggio_primiera(prese_eo)
    if pn > pe:
        return 1, 0
    if pe > pn:
        return 0, 1
    return 0, 0


def calcola_napula(prese: list[Carta]) -> int:
    """
    Napula: Asso+2+3 di Ori = 3 pt, +1 per ogni carta consecutiva aggiuntiva (4,5,6,7).
    Sequenza deve partire dall'Asso.
    """
    ori = [c.valore for c in prese if c.seme == "Ori"]
    if 1 not in ori:
        return 0
    consecutivi = 1
    v = 1
    while v + 1 in ori:
        v += 1
        consecutivi += 1
    if consecutivi >= 3:
        return consecutivi  # 3 pt per A+2+3, +1 per ogni successivo
    return 0


def calcola_napula_squadre(prese_ns: list[Carta], prese_eo: list[Carta]) -> tuple[int, int]:
    nn = calcola_napula(prese_ns)
    ne = calcola_napula(prese_eo)
    return nn, ne


# --- Turno umano ---

def stampa_tavolo(tavolo: list[Carta]):
    if tavolo:
        print("TAVOLO:", " | ".join(str(c) for c in tavolo))
    else:
        print("TAVOLO: (vuoto)")


def visualizza_stato(
    tavolo: list[Carta],
    scope_ns: int,
    scope_eo: int,
    punteggio_ns: int = 0,
    punteggio_eo: int = 0,
    mano_sud: list[Carta] | None = None,
) -> None:
    """
    Visualizza lo stato del gioco con matplotlib: tavolo, punteggi, mano del giocatore.
    """
    if not HAS_MATPLOTLIB:
        return
    fig, ax = plt.subplots(1, 1, figsize=(12, 8))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 10)
    ax.set_aspect("equal")
    ax.axis("off")

    # Colori semi (approssimativi)
    colori = {"Ori": "#FFD700", "Coppe": "#E63946", "Spade": "#1D3557", "Bastoni": "#2A9D8F"}
    bk = "#2D5016"  # felt green

    # Sfondo
    ax.set_facecolor(bk)
    fig.patch.set_facecolor(bk)

    # Punteggio
    ax.text(6, 9.2, f"NS: {punteggio_ns}  |  EO: {punteggio_eo}", fontsize=14, ha="center", color="white")
    ax.text(6, 8.6, f"Scope NS: {scope_ns}  |  EO: {scope_eo}", fontsize=11, ha="center", color="#ddd")

    # Tavolo
    ax.text(6, 6.2, "TAVOLO", fontsize=12, ha="center", color="white")
    if tavolo:
        n = len(tavolo)
        w = 1.2
        start_x = 6 - (n * w) / 2 + w / 2
        for i, c in enumerate(tavolo):
            x = start_x + i * w
            col = colori.get(c.seme, "#fff")
            rect = mpatches.FancyBboxPatch((x - 0.4, 4.5), 0.8, 1.2, boxstyle="round,pad=0.02", facecolor="white", edgecolor=col, linewidth=2)
            ax.add_patch(rect)
            nome = NOMI_VALORI.get(c.valore, str(c.valore))
            ax.text(x, 5.1, nome[:2], fontsize=8, ha="center")
            ax.text(x, 4.85, c.seme[0], fontsize=7, ha="center", color=col)
    else:
        ax.text(6, 5.1, "(vuoto)", fontsize=10, ha="center", color="#888")

    # Mano Sud
    if mano_sud:
        ax.text(6, 3.2, "TUA MANO", fontsize=12, ha="center", color="white")
        for i, c in enumerate(mano_sud):
            x = 2 + i * 1.5
            col = colori.get(c.seme, "#fff")
            rect = mpatches.FancyBboxPatch((x - 0.45, 1.5), 0.9, 1.4, boxstyle="round,pad=0.02", facecolor="white", edgecolor=col, linewidth=2)
            ax.add_patch(rect)
            nome = NOMI_VALORI.get(c.valore, str(c.valore))
            ax.text(x, 2.2, nome, fontsize=9, ha="center")
            ax.text(x, 1.9, c.seme, fontsize=8, ha="center", color=col)
            ax.text(x, 1.65, str(i + 1), fontsize=8, ha="center", color="#666")

    plt.tight_layout()
    plt.savefig("scopone_stato.png", dpi=120, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    print("  [Stato salvato in scopone_stato.png]")


def turno_umano(mano: list[Carta], tavolo: list[Carta], scope_ns: int, scope_eo: int) -> tuple[Carta, list[Carta] | None]:
    """Turno del giocatore umano (Sud)."""
    stampa_tavolo(tavolo)
    print("TUA MANO:")
    for i, c in enumerate(mano, 1):
        print(f"  {i}. {c}")
    print(f"Scope — NS: {scope_ns}  |  EO: {scope_eo}")
    print()

    while True:
        try:
            scelta = input("Scegli numero carta (1-{}): ".format(len(mano)))
            idx = int(scelta) - 1
            if 0 <= idx < len(mano):
                carta = mano[idx]
                break
        except ValueError:
            pass
        print("Scelta non valida.")

    opzioni = catture_valide(carta, tavolo)

    if not opzioni:
        return carta, None

    if len(opzioni) == 1:
        return carta, opzioni[0]

    print("Catture possibili:")
    for i, cat in enumerate(opzioni, 1):
        print(f"  {i}. Prendi: {' + '.join(str(c) for c in cat)}")
    while True:
        try:
            scelta_cat = input("Scegli cattura (1-{}): ".format(len(opzioni)))
            idx_cat = int(scelta_cat) - 1
            if 0 <= idx_cat < len(opzioni):
                return carta, opzioni[idx_cat]
        except ValueError:
            pass
        print("Scelta non valida.")


# --- Main loop ---

def gioca_mano(
    mani: list[list[Carta]],
    punteggio_ns: int,
    punteggio_eo: int,
    scope_ns: int,
    scope_eo: int,
) -> tuple[int, int, bool]:
    """
    Esegue una mano completa. Ritorna (punteggio_ns, punteggio_eo, partita_finita).
    """
    tavolo: list[Carta] = []
    prese_ns: list[Carta] = []
    prese_eo: list[Carta] = []
    ultimo_catturante: str | None = None

    # Ordine: Est(0), Nord(1), Ovest(2), Sud(3) - antiorario
    giocatore_idx = 0
    carte_giocate = 0
    totale_giocate = 40

    while any(mani):
        giocatore = GIOCATORI[giocatore_idx]
        mano = mani[giocatore_idx]
        if not mano:
            giocatore_idx = (giocatore_idx + 1) % 4
            continue

        ultima_giocata_mano = carte_giocate == totale_giocate - 1

        print("\n" + "=" * 50)
        print(f"Turno di {giocatore}")
        print("=" * 50)

        if giocatore == "Sud":
            visualizza_stato(tavolo, scope_ns, scope_eo, punteggio_ns, punteggio_eo, mano)
            carta, cattura = turno_umano(mano, tavolo, scope_ns, scope_eo)
        else:
            carta, cattura = turno_ai(mano, tavolo, ultima_mano=ultima_giocata_mano)
            print(f"{giocatore} gioca: {carta}")
            if cattura:
                print(f"  → Prende: {' + '.join(str(c) for c in cattura)}")
            else:
                print("  → Lascia sul tavolo")

        mano.remove(carta)
        tavolo, prese_ns, prese_eo, scope_ns, scope_eo, _ = risolvi_giocata(
            carta, cattura, tavolo, prese_ns, prese_eo,
            scope_ns, scope_eo, giocatore, ultima_giocata_mano
        )

        if cattura:
            ultimo_catturante = giocatore

        carte_giocate += 1
        giocatore_idx = (giocatore_idx + 1) % 4

    # Assegna carte rimanenti all'ultimo catturante
    if tavolo and ultimo_catturante:
        squadra = quale_squadra(ultimo_catturante)
        if "Nord" in squadra or "Sud" in squadra:
            prese_ns.extend(tavolo)
        else:
            prese_eo.extend(tavolo)

    # Calcolo punteggio mano
    pt_carte_ns, pt_carte_eo = calcola_carte(prese_ns, prese_eo)
    pt_ori_ns, pt_ori_eo = calcola_ori(prese_ns, prese_eo)
    pt_sb_ns, pt_sb_eo = calcola_settebello(prese_ns, prese_eo)
    pt_prim_ns, pt_prim_eo = calcola_primiera(prese_ns, prese_eo)
    pt_nap_ns, pt_nap_eo = calcola_napula_squadre(prese_ns, prese_eo)

    pt_mano_ns = pt_carte_ns + pt_ori_ns + pt_sb_ns + pt_prim_ns + scope_ns + pt_nap_ns
    pt_mano_eo = pt_carte_eo + pt_ori_eo + pt_sb_eo + pt_prim_eo + scope_eo + pt_nap_eo

    punteggio_ns += pt_mano_ns
    punteggio_eo += pt_mano_eo

    print("\n" + "=" * 50)
    print("FINE MANO - Punteggio")
    print("=" * 50)
    print(f"Carte   : NS {pt_carte_ns} - EO {pt_carte_eo}")
    print(f"Ori     : NS {pt_ori_ns} - EO {pt_ori_eo}")
    print(f"Settebello: NS {pt_sb_ns} - EO {pt_sb_eo}")
    print(f"Primiera: NS {pt_prim_ns} - EO {pt_prim_eo}")
    print(f"Scope   : NS {scope_ns} - EO {scope_eo}")
    print(f"Napula  : NS {pt_nap_ns} - EO {pt_nap_eo}")
    print("-" * 30)
    print(f"Punteggio mano: NS {pt_mano_ns} - EO {pt_mano_eo}")
    print(f"PUNTEGGIO TOTALE: NS {punteggio_ns} - EO {punteggio_eo}")
    print("=" * 50)

    # Condizione di vittoria
    if punteggio_ns >= 21 or punteggio_eo >= 21:
        if punteggio_ns > punteggio_eo:
            print("\n*** VITTORIA SQUADRA NS! ***")
        elif punteggio_eo > punteggio_ns:
            print("\n*** VITTORIA SQUADRA EO! ***")
        else:
            print("\n*** PAREGGIO - Altra mano! ***")
            return punteggio_ns, punteggio_eo, False
        return punteggio_ns, punteggio_eo, True

    return punteggio_ns, punteggio_eo, False


def main():
    print("\n*** SCOPONE SCIENTIFICO ***")
    print("Tu giochi come Sud, in squadra con Nord.")
    print("Turno: Est → Nord → Ovest → Sud (antiorario)\n")

    punteggio_ns = 0
    punteggio_eo = 0
    mano_num = 1

    while True:
        print(f"\n{'#' * 50}")
        print(f"MANO {mano_num}")
        print(f"{'#' * 50}")

        mazzo = crea_mazzo()
        mani = distribuisci(mazzo)
        scope_ns = 0
        scope_eo = 0

        punteggio_ns, punteggio_eo, finita = gioca_mano(
            mani, punteggio_ns, punteggio_eo, scope_ns, scope_eo
        )

        if finita:
            break

        mano_num += 1
        input("\nPremi Invio per la prossima mano...")

    print("\nPartita conclusa.")


if __name__ == "__main__":
    main()
