import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError
from sklearn.ensemble import RandomForestRegressor

st.set_page_config(page_title="Estimation du ménage", page_icon="🧹", layout="centered")

# La base contient les comptes et uniquement des empreintes de mots de passe.
# Sur un serveur, définissez HOTEL_DB_PATH vers un stockage persistant et protégé.
DB_PATH = Path(os.environ.get("HOTEL_DB_PATH", str(Path(__file__).with_name("hotel_accounts.sqlite3"))))


def lire_secret(nom):
    """Lit un secret du serveur ou du gestionnaire de secrets Streamlit."""
    valeur = os.environ.get(nom)
    if valeur:
        return valeur
    try:
        return st.secrets.get(nom, "")
    except (KeyError, StreamlitSecretNotFoundError):
        return ""


def ouvrir_base():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connexion = sqlite3.connect(DB_PATH, timeout=15)
    connexion.row_factory = sqlite3.Row
    return connexion


def empreinte_mot_de_passe(mot_de_passe, sel=None):
    sel = sel or secrets.token_bytes(16)
    empreinte = hashlib.scrypt(
        mot_de_passe.encode("utf-8"), salt=sel, n=2**14, r=8, p=1, dklen=32
    )
    return f"{sel.hex()}:{empreinte.hex()}"


def verifier_mot_de_passe(mot_de_passe, valeur_stockee):
    try:
        sel_hex, empreinte_hex = valeur_stockee.split(":", 1)
        attendue = bytes.fromhex(empreinte_hex)
        calculee = bytes.fromhex(empreinte_mot_de_passe(mot_de_passe, bytes.fromhex(sel_hex)).split(":", 1)[1])
        return hmac.compare_digest(calculee, attendue)
    except (ValueError, TypeError):
        return False


def initialiser_base():
    with ouvrir_base() as connexion:
        connexion.execute(
            """CREATE TABLE IF NOT EXISTS comptes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identifiant TEXT NOT NULL UNIQUE COLLATE NOCASE,
                nom_hotel TEXT NOT NULL,
                empreinte_mot_de_passe TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'hotel')),
                actif INTEGER NOT NULL DEFAULT 1,
                expiration TEXT,
                cree_le TEXT NOT NULL
            )"""
        )
        utilisateur_admin = lire_secret("HOTEL_ADMIN_USER").strip()
        mot_de_passe_admin = lire_secret("HOTEL_ADMIN_PASSWORD")
        if utilisateur_admin and mot_de_passe_admin:
            if len(mot_de_passe_admin) < 12:
                raise ValueError("HOTEL_ADMIN_PASSWORD doit contenir au moins 12 caractères.")
            existe = connexion.execute(
                "SELECT id FROM comptes WHERE identifiant = ?", (utilisateur_admin,)
            ).fetchone()
            if not existe:
                connexion.execute(
                    """INSERT INTO comptes
                    (identifiant, nom_hotel, empreinte_mot_de_passe, role, actif, expiration, cree_le)
                    VALUES (?, ?, ?, 'admin', 1, NULL, ?)""",
                    (
                        utilisateur_admin,
                        "Administration",
                        empreinte_mot_de_passe(mot_de_passe_admin),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )


def chercher_compte(identifiant):
    with ouvrir_base() as connexion:
        return connexion.execute(
            "SELECT * FROM comptes WHERE identifiant = ?", (identifiant,)
        ).fetchone()


def date_expiree(compte):
    if compte["role"] == "admin":
        return False
    return not compte["expiration"] or compte["expiration"] < datetime.now(timezone.utc).date().isoformat()


def authentifier(identifiant, mot_de_passe):
    compte = chercher_compte(identifiant.strip())
    if (
        compte is None
        or not compte["actif"]
        or date_expiree(compte)
        or not verifier_mot_de_passe(mot_de_passe, compte["empreinte_mot_de_passe"])
    ):
        return None
    return {"identifiant": compte["identifiant"], "role": compte["role"]}


def enregistrer_compte_hotel(identifiant, nom_hotel, mot_de_passe, expiration):
    with ouvrir_base() as connexion:
        connexion.execute(
            """INSERT INTO comptes
            (identifiant, nom_hotel, empreinte_mot_de_passe, role, actif, expiration, cree_le)
            VALUES (?, ?, ?, 'hotel', 1, ?, ?)""",
            (
                identifiant.strip(),
                nom_hotel.strip(),
                empreinte_mot_de_passe(mot_de_passe),
                expiration.isoformat(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def charger_comptes_hotels():
    with ouvrir_base() as connexion:
        return connexion.execute(
            "SELECT id, identifiant, nom_hotel, actif, expiration FROM comptes "
            "WHERE role = 'hotel' ORDER BY nom_hotel COLLATE NOCASE"
        ).fetchall()


def mettre_a_jour_compte(compte_id, actif, expiration):
    with ouvrir_base() as connexion:
        connexion.execute(
            "UPDATE comptes SET actif = ?, expiration = ? WHERE id = ? AND role = 'hotel'",
            (int(actif), expiration.isoformat(), compte_id),
        )


def modele_synthetique():
    """Génère des données artificielles en mémoire et entraîne le modèle."""
    rng = np.random.default_rng(42)
    nombre_exemples = 2500
    nuits = rng.integers(1, 15, size=nombre_exemples)
    personnes = rng.integers(1, 6, size=nombre_exemples)
    petit_dejeuner = rng.integers(0, 2, size=nombre_exemples)
    duree = np.clip(
        18 + nuits * 2.2 + personnes * 5.5 + petit_dejeuner * 12
        + rng.normal(0, 6, size=nombre_exemples),
        15,
        120,
    )
    entrees = np.column_stack((nuits, personnes, petit_dejeuner))
    modele = RandomForestRegressor(
        n_estimators=160, random_state=42, min_samples_leaf=2, n_jobs=-1
    )
    modele.fit(entrees, duree)
    return modele


try:
    initialiser_base()
except (OSError, sqlite3.Error, ValueError) as erreur:
    st.error(f"La base des comptes n'a pas pu être initialisée : {erreur}")
    st.stop()

if "compte_connecte" not in st.session_state:
    st.session_state.compte_connecte = None

# Relecture côté serveur à chaque exécution Streamlit : désactivation et expiration
# prennent donc effet même si l'utilisateur a encore un onglet ouvert.
utilisateur = st.session_state.compte_connecte
if utilisateur:
    compte_actuel = chercher_compte(utilisateur["identifiant"])
    if compte_actuel is None or not compte_actuel["actif"] or date_expiree(compte_actuel):
        st.session_state.compte_connecte = None
        utilisateur = None
    else:
        utilisateur = {"identifiant": compte_actuel["identifiant"], "role": compte_actuel["role"]}

if utilisateur is None:
    st.caption(":material/hotel: ESPACE HÔTELIER")
    st.title("Bienvenue")
    st.write("Connectez-vous à votre espace sécurisé pour estimer le temps de remise en état des chambres.")
    with st.form("connexion"):
        identifiant = st.text_input("Identifiant")
        mot_de_passe = st.text_input("Mot de passe", type="password")
        soumettre = st.form_submit_button("Se connecter", type="primary")
    if soumettre:
        session = authentifier(identifiant, mot_de_passe)
        if session:
            st.session_state.compte_connecte = session
            st.rerun()
        st.error("Connexion impossible. Vérifiez vos identifiants ou contactez l'administrateur.")

    # Une première configuration nécessite les variables d'environnement du serveur.
    with ouvrir_base() as connexion:
        admin_present = connexion.execute(
            "SELECT 1 FROM comptes WHERE role = 'admin' LIMIT 1"
        ).fetchone()
    if not admin_present:
        st.info(
            "Aucun administrateur configuré. Définissez HOTEL_ADMIN_USER et "
            "HOTEL_ADMIN_PASSWORD dans l'environnement du serveur, puis redémarrez l'application."
        )
    st.stop()

st.sidebar.write(f"Connecté : **{utilisateur['identifiant']}**")
if st.sidebar.button("Se déconnecter"):
    st.session_state.compte_connecte = None
    st.rerun()

if utilisateur["role"] == "admin":
    st.caption(":material/admin_panel_settings: ESPACE ADMINISTRATEUR")
    st.title("Gestion des hôtels")
    st.caption("Crée les accès, prolonge un abonnement ou désactive un compte.")
    onglet_creation, onglet_gestion = st.tabs(["Créer un compte", "Gérer les comptes"])

    with onglet_creation:
        with st.form("creer_compte_hotel"):
            nom_hotel = st.text_input("Nom de l'hôtel")
            nouvel_identifiant = st.text_input("Identifiant du compte")
            nouveau_mot_de_passe = st.text_input("Mot de passe initial (12 caractères minimum)", type="password")
            expiration_initiale = st.date_input("Date d'expiration", value=date.today())
            creer = st.form_submit_button("Créer le compte", type="primary")
        if creer:
            if not nom_hotel.strip() or not nouvel_identifiant.strip():
                st.error("Indiquez le nom de l'hôtel et un identifiant.")
            elif len(nouveau_mot_de_passe) < 12:
                st.error("Le mot de passe doit contenir au moins 12 caractères.")
            elif expiration_initiale < date.today():
                st.error("La date d'expiration doit être aujourd'hui ou une date future.")
            else:
                try:
                    enregistrer_compte_hotel(
                        nouvel_identifiant, nom_hotel, nouveau_mot_de_passe, expiration_initiale
                    )
                    st.success("Compte créé et activé.")
                except sqlite3.IntegrityError:
                    st.error("Cet identifiant est déjà utilisé.")

    with onglet_gestion:
        comptes = charger_comptes_hotels()
        if not comptes:
            st.info("Aucun compte hôtel pour le moment.")
        else:
            for compte in comptes:
                statut = "Actif" if compte["actif"] else "Désactivé"
                st.write(
                    f"**{compte['nom_hotel']}** — `{compte['identifiant']}` — {statut} — "
                    f"expiration : {compte['expiration']}"
                )
            options = {f"{c['nom_hotel']} ({c['identifiant']})": c for c in comptes}
            choix = st.selectbox("Compte à modifier", list(options))
            compte = options[choix]
            with st.form("modifier_compte"):
                actif = st.checkbox("Compte actif", value=bool(compte["actif"]))
                expiration = st.date_input(
                    "Date d'expiration (prolonger en choisissant une date ultérieure)",
                    value=date.fromisoformat(compte["expiration"]),
                )
                sauvegarder = st.form_submit_button("Enregistrer les changements")
            if sauvegarder:
                mettre_a_jour_compte(compte["id"], actif, expiration)
                st.success("Compte mis à jour.")
                st.rerun()
else:
    with ouvrir_base() as connexion:
        details = connexion.execute(
            "SELECT nom_hotel, expiration FROM comptes WHERE identifiant = ?",
            (utilisateur["identifiant"],),
        ).fetchone()
    st.caption(":material/hotel: ESPACE HÔTELIER")
    st.title("Estimation du temps de ménage")
    st.caption(f"{details['nom_hotel']} · Accès valide jusqu’au {details['expiration']}")
    st.write("Préparez l’organisation de vos équipes après le départ d’un client.")
    st.warning(
        "Modèle de démonstration : les prédictions sont basées uniquement sur des données "
        "artificielles générées par l'application. Elles ne constituent pas une mesure réelle."
    )
    with st.form("formulaire_estimation"):
        nombre_nuits = st.number_input("Nombre de nuits", min_value=1, max_value=30, value=2, step=1)
        nombre_personnes = st.number_input("Nombre de personnes", min_value=1, max_value=10, value=2, step=1)
        petit_dejeuner = st.checkbox("Petit-déjeuner consommé dans la chambre")
        calculer = st.form_submit_button("Calculer", type="primary")
    if calculer:
        modele = modele_synthetique()
        entrees = np.array([[nombre_nuits, nombre_personnes, int(petit_dejeuner)]], dtype=float)
        duree_minutes = float(modele.predict(entrees)[0])
        col_minutes, col_heures = st.columns(2)
        col_minutes.metric("En minutes", f"{duree_minutes:.0f} min")
        col_heures.metric("En heures", f"{duree_minutes / 60:.2f} h")
        st.caption("L'estimation en heures correspond aux minutes divisées par 60.")
