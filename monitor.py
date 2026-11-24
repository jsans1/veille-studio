"""Veille d'annonces de location.

Pour chaque page de sites.yaml :
- charge la page (navigateur Chromium headless, ou simple requête HTTP),
- relève les liens d'annonces,
- compare avec les liens déjà vus (state/seen.json),
- envoie une notification ntfy pour chaque nouvelle annonce.

Variables d'environnement :
  NTFY_TOPIC   nom du sujet ntfy (obligatoire sauf en mode DEBUG)
  NTFY_SERVER  serveur ntfy (défaut : https://ntfy.sh)
  DEBUG=1      affiche ce qui est trouvé, n'envoie rien, ne sauvegarde rien
  TEST_NOTIF=1 envoie une notification de test et s'arrête
"""

import json
import os
import re
import sys
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
import yaml
from bs4 import BeautifulSoup

STATE_FILE = "state/seen.json"
SITES_FILE = "sites.yaml"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
DEFAULT_PATTERN = r"\d{4,}"  # la plupart des annonces ont un identifiant numérique
GLOBAL_EXCLUDE = r"(^tel:|^mailto:|^javascript:|[?&]page=|/page/\d|/agences?/?$|/agence-immobiliere/[^/]+/?$|/contact|/estimation|/actus?/|/blog|/conseils?)"
TRACKING_PARAMS = re.compile(r"^(utm_|fbclid|gclid|xtor|at_|_ga)", re.I)
MAX_NOTIFS_PER_SITE = 8  # au-delà : probablement un changement de mise en page
FAIL_ALERT_AFTER = 3

DEBUG = os.environ.get("DEBUG") == "1"


# ---------------------------------------------------------------- utilitaires

def normalize(url: str, keep_query: bool = True) -> str:
    p = urlparse(url)
    query = ""
    if keep_query and p.query:
        params = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                  if not TRACKING_PARAMS.match(k)]
        query = urlencode(sorted(params))
    return urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip("/") or "/", "", query, ""))


def extract_links(html: str, base_url: str, pattern: str, exclude: str | None,
                  keep_query: bool) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_host = urlparse(base_url).netloc.lower().removeprefix("www.")
    page_self = normalize(base_url, keep_query)
    rx = re.compile(pattern)
    rx_ex = re.compile(exclude) if exclude else None
    rx_global = re.compile(GLOBAL_EXCLUDE, re.I)
    found: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or rx_global.search(href):
            continue
        absolute = urljoin(base_url, href)
        p = urlparse(absolute)
        if p.scheme not in ("http", "https"):
            continue
        if p.netloc.lower().removeprefix("www.") != base_host:
            continue
        target = p.path + ("?" + p.query if p.query else "")
        if not rx.search(target):
            continue
        if rx_ex and rx_ex.search(target):
            continue
        norm = normalize(absolute, keep_query)
        if norm == page_self or norm in found:
            continue
        found.append(norm)
    return found


def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)


def notify(title: str, message: str, click: str | None = None, tags=None, priority=3) -> None:
    topic = os.environ.get("NTFY_TOPIC")
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    if DEBUG or not topic:
        print(f"[notif simulée] {title} | {message} | {click or ''}")
        return
    payload = {"topic": topic, "title": title, "message": message,
               "priority": priority, "tags": tags or []}
    if click:
        payload["click"] = click
    try:
        requests.post(server, json=payload, timeout=15).raise_for_status()
    except requests.RequestException as e:
        print(f"Échec de la notification : {e}", file=sys.stderr)


# ---------------------------------------------------------------- chargement

class Fetcher:
    def __init__(self):
        self._pw = None
        self._browser = None
        self._ctx = None
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept-Language": "fr-FR,fr;q=0.9"})

    def http(self, url: str) -> str:
        r = self.session.get(url, timeout=30)
        r.raise_for_status()
        return r.text

    def browser(self, url: str, wait_ms: int) -> str:
        if self._browser is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            exe = os.environ.get("CHROMIUM_PATH") or None  # pour tester hors GitHub
            self._browser = self._pw.chromium.launch(executable_path=exe)
            self._ctx = self._browser.new_context(user_agent=UA, locale="fr-FR",
                                                  viewport={"width": 1366, "height": 900})
        page = self._ctx.new_page()
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if resp is not None and resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}")
            page.wait_for_timeout(wait_ms)
            for _ in range(4):  # fait charger les listes paresseuses
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(600)
            return page.content()
        finally:
            page.close()

    def close(self):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()


# ---------------------------------------------------------------- programme

def run() -> int:
    if os.environ.get("TEST_NOTIF") == "1":
        notify("Test veille studio", "Si tu lis ceci, les notifications marchent.",
               tags=["white_check_mark"])
        return 0

    with open(SITES_FILE, encoding="utf-8") as f:
        sites = yaml.safe_load(f)["sites"]

    state = load_state()
    seen = state.setdefault("seen", {})
    fails = state.setdefault("fails", {})
    fetcher = Fetcher()
    errors = 0

    try:
        for site in sites:
            key = site["name"]
            url = site["url"]
            mode = site.get("mode", "browser")
            keep_query = site.get("keep_query", False)
            try:
                html = fetcher.http(url) if mode == "http" else fetcher.browser(url, site.get("wait", 4000))
                links = extract_links(html, url, site.get("pattern", DEFAULT_PATTERN),
                                      site.get("exclude"), keep_query)
            except Exception as e:  # noqa: BLE001 - on veut continuer sur les autres sites
                errors += 1
                fails[key] = fails.get(key, 0) + 1
                print(f"ERREUR {key}: {e}")
                if fails[key] == FAIL_ALERT_AFTER and not DEBUG:
                    notify(f"Page en panne : {key}",
                           f"{FAIL_ALERT_AFTER} échecs d'affilée ({str(e)[:120]}). Vérifie l'URL.",
                           click=url, tags=["warning"], priority=2)
                continue

            fails.pop(key, None)

            if DEBUG:
                print(f"\n== {key} ({mode}) : {len(links)} liens d'annonces")
                for l in links[:6]:
                    print(f"   {l}")
                continue

            previous = set(seen.get(key, []))
            first_time = key not in seen
            new = [l for l in links if l not in previous]
            # on garde aussi les anciens liens pour ne pas re-notifier une annonce
            # qui disparaît puis réapparaît dans la liste
            seen[key] = sorted(previous | set(links))[-500:]

            if first_time:
                print(f"{key}: première passe, {len(links)} liens mémorisés sans notification")
                continue
            if not new:
                print(f"{key}: rien de nouveau")
                continue

            print(f"{key}: {len(new)} nouvelle(s) annonce(s)")
            if len(new) > MAX_NOTIFS_PER_SITE:
                notify(f"{key} : {len(new)} nouveaux liens",
                       "Beaucoup de nouveautés d'un coup, la page a peut-être changé. Ouvre-la pour vérifier.",
                       click=url, tags=["house"])
            else:
                for l in new:
                    notify(f"Nouvelle annonce : {key}", l, click=l, tags=["house"], priority=4)
            time.sleep(1)
    finally:
        fetcher.close()

    if not DEBUG:
        save_state(state)
    print(f"\nTerminé. {len(sites)} pages, {errors} erreur(s).")
    return 0


if __name__ == "__main__":
    sys.exit(run())
