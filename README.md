# Veille studio

Vérifie toutes les 20 minutes (lundi-samedi, 7h-20h40) une cinquantaine de pages d'annonces et envoie une notification sur ton téléphone dès qu'une nouvelle annonce apparaît.

## Installation (15 minutes)

### 1. Téléphone : ntfy
1. Installe l'appli **ntfy** (App Store ou Google Play, gratuite, sans compte).
2. Appuie sur **+** et abonne-toi à ton sujet (le même nom que le secret `NTFY_TOPIC`).

### 2. GitHub : le dépôt
1. Sur github.com, crée un nouveau dépôt nommé `veille-studio`, en **Public** (en privé, les minutes gratuites ne suffisent pas pour tourner toutes les 20 minutes).
2. Clique sur **uploading an existing file**, puis glisse **tout le contenu** de ce dossier, y compris le dossier `.github` (sur Mac, Cmd+Maj+. affiche les dossiers cachés dans le Finder). Valide avec **Commit changes**.
3. Vérifie que le fichier `.github/workflows/veille.yml` apparaît bien dans le dépôt.

### 3. GitHub : le secret
1. Dans le dépôt : **Settings > Secrets and variables > Actions > New repository secret**.
2. Name : `NTFY_TOPIC`. Secret : le nom de ton sujet ntfy.

### 4. Premiers lancements (onglet Actions)
1. Ouvre l'onglet **Actions**. Si GitHub demande d'activer les workflows, accepte.
2. Clique sur **Veille studio > Run workflow**, choisis **notif**, lance. Tu dois recevoir « Test veille studio » sur ton téléphone.
3. Relance avec **test** : rien n'est envoyé, mais le journal affiche pour chaque page le nombre de liens d'annonces trouvés. Copie ce journal à Claude pour ajuster les pages qui renvoient 0 lien ou une erreur.
4. Relance avec **normal** : le script mémorise les annonces actuelles sans t'envoyer de notification.
5. Ensuite, tout tourne seul.

## Au quotidien
- Chaque notification contient le lien de l'annonce : touche-la pour l'ouvrir.
- Si une page tombe en panne 3 fois de suite, tu reçois « Page en panne » avec le nom de la page.
- Si une page envoie beaucoup de nouveautés d'un coup, tu reçois un seul message te demandant de vérifier la page (souvent un changement de mise en page).

## Modifier la liste
Tout est dans `sites.yaml` (bouton crayon sur GitHub pour l'éditer). Supprime un bloc pour retirer une page, copie un bloc pour en ajouter une.

## Arrêter
Onglet **Actions > Veille studio > ... > Disable workflow**. Une fois le studio trouvé, tu peux aussi supprimer le dépôt.
