# Estimation du temps de ménage

Application de démonstration Streamlit : elle estime un temps de ménage en minutes et en heures à partir de trois informations. Le modèle est entraîné au lancement sur des données artificielles générées en mémoire. Il ne lit aucun fichier Excel et ses résultats ne constituent pas des mesures réelles.

## Lancer en local sous Windows

Depuis ce dossier, dans PowerShell :

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Configurez `HOTEL_ADMIN_USER` et `HOTEL_ADMIN_PASSWORD` dans l'environnement du serveur avant le premier démarrage. Le compte admin est créé dans la base SQLite locale `hotel_accounts.sqlite3`; cette base est exclue de Git.

## Publication

Publiez le code dans un dépôt GitHub, puis sélectionnez ce dépôt et `app.py` dans Streamlit Community Cloud. Configurez les variables d'environnement/secrets dans les paramètres de l'application hébergée, jamais dans le code ni dans Git.

**Avant tout usage réel :** cette version utilise une base SQLite locale. Une plateforme dont le disque peut être réinitialisé ou une application exécutée sur plusieurs instances nécessite une base de données persistante partagée. Le fichier Excel des hôtels n'est pas encore importé par cette démonstration. Ne transmettez pas de fichiers contenant des données clients ou personnelles avant d'avoir défini un flux d'import et des règles de confidentialité.
