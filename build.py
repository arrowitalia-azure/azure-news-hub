#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Azure News Hub - Arrow Italia ECS
Script di build (GitHub Actions ready).

Cosa fa a ogni esecuzione:
  1. legge i feed ufficiali Microsoft:
       - Microsoft Community Hub, blog della sezione Azure (fonte principale)
       - Microsoft Azure Blog
       - Azure Updates
       - Microsoft Learn (voci curate + ritiri in evidenza + annunci Partner Center)
  2. tiene solo contenuti pertinenti ad Azure, elimina i duplicati
  3. assegna categoria (AI, Infrastructure, Security, Networking, Data, Apps),
     servizio Azure, stato (GA / Anteprima / Ritiro), tempo di lettura stimato
  4. traduce titolo e sintesi in italiano con Azure AI Translator
     (i nomi ufficiali dei prodotti NON vengono tradotti) e salva una cache
  5. genera index.html (pagina completa, CSS e JS inclusi) e news.json

Nessuna dipendenza esterna: solo libreria standard di Python 3.9+.

Variabili d'ambiente (GitHub Secrets) per la traduzione:
  AZURE_TRANSLATOR_KEY      chiave della risorsa Azure AI Translator
  AZURE_TRANSLATOR_REGION   regione della risorsa (es. westeurope, italynorth)
  AZURE_TRANSLATOR_ENDPOINT opzionale (default endpoint globale)
Senza chiave il sito viene comunque generato: le notizie restano in inglese
e sono segnalate come "Non tradotto".
"""
import base64, hashlib, html, json, os, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit
import xml.etree.ElementTree as ET

try:
    from zoneinfo import ZoneInfo
    TZ_ROME = ZoneInfo("Europe/Rome")
except Exception:  # pragma: no cover
    TZ_ROME = timezone(timedelta(hours=1))

HERE = os.path.dirname(os.path.abspath(__file__))
NOW = datetime.now(TZ_ROME)

# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------
MAX_AGE_DAYS = 60          # notizie più vecchie vengono scartate
MAX_PER_FEED = 15          # massimo elementi letti per singolo feed
MAX_ITEMS = 150            # massimo notizie in pagina
FETCH_TIMEOUT = 25
USER_AGENT = "AzureNewsHub/2.0 (+https://arrowitalia-azure.github.io/azure-news-hub/)"

HUB_RSS = "https://techcommunity.microsoft.com/t5/s/gxcuf89792/rss/board?board.id={}"
HUB_SECTION = "https://techcommunity.microsoft.com/category/Azure"

# Blog del Microsoft Community Hub (sezione Azure).
# Un board che non risponde viene semplicemente saltato (vedi log dell'Action).
HUB_BOARDS = [
    "AzureInfrastructureBlog", "AzureStorageBlog", "AzureNetworkingBlog",
    "AppsonAzureBlog", "AzureArcBlog", "IntegrationsonAzureBlog",
    "MessagingonAzureBlog", "OracleonAzureBlog", "FinOpsBlog",
    "AzureHighPerformanceComputingBlog", "AzureDataBlog", "AzurePaaSBlog",
    "AzureGovernanceandManagementBlog", "AzureMigrationBlog",
    "AzureVirtualDesktopBlog", "AzureToolsBlog", "AzureArchitectureBlog",
    "Azure-AI-Foundry-Blog", "MicrosoftDefenderCloudBlog",
    "AzureObservabilityBlog", "AzureDatabaseforPostgreSQLBlog",
    "AzureSQLBlog", "AzureCompute", "AzureConfidentialComputingBlog",
]
# Suggerimento di categoria in base al blog di provenienza
BOARD_HINT = {
    "AzureStorageBlog": "Data", "AzureDataBlog": "Data", "OracleonAzureBlog": "Data",
    "AzureDatabaseforPostgreSQLBlog": "Data", "AzureSQLBlog": "Data",
    "AzureNetworkingBlog": "Networking",
    "AppsonAzureBlog": "Apps", "IntegrationsonAzureBlog": "Apps",
    "MessagingonAzureBlog": "Apps", "AzurePaaSBlog": "Apps", "AzureToolsBlog": "Apps",
    "Azure-AI-Foundry-Blog": "AI",
    "MicrosoftDefenderCloudBlog": "Security", "AzureConfidentialComputingBlog": "Security",
}

FEED_BLOG = "https://azure.microsoft.com/en-us/blog/feed/"
FEED_UPDATES = "https://www.microsoft.com/releasecommunications/api/v2/azure/rss"
L_BLOG = "https://azure.microsoft.com/en-us/blog/"
L_UPD = "https://azure.microsoft.com/en-us/updates/"
L_GITHUB = "https://github.com/Azure"
_MONTHS_EN = ["january","february","march","april","may","june","july","august",
              "september","october","november","december"]
L_LEARN_PARTNER = ("https://learn.microsoft.com/en-us/partner-center/announcements/"
                   f"{NOW.year}-{_MONTHS_EN[NOW.month-1]}")

# Escludi contenuti non pertinenti (newsletter, call di community, ecc.)
EXCLUDE_PATTERNS = [r"\bnewsletter\b", r"\bcommunity call\b", r"\bwebinar recap\b",
                    r"\bhiring\b", r"\bmeetup\b"]

MESI = ["gennaio","febbraio","marzo","aprile","maggio","giugno","luglio",
        "agosto","settembre","ottobre","novembre","dicembre"]

# Nomi ufficiali dei prodotti: usati per riconoscere il servizio e
# per proteggerli dalla traduzione (non vengono mai tradotti).
SERVICES = [
    "Azure Kubernetes Service", "AKS", "Azure Virtual Machines", "Azure Virtual Desktop",
    "Microsoft Defender for Cloud", "Azure AI Foundry", "Microsoft Foundry", "Foundry Agent Service",
    "Azure OpenAI", "Azure AI Search", "Azure Machine Learning", "Azure AI Services",
    "Azure SRE Agent", "Azure Copilot", "GitHub Copilot", "Microsoft Copilot",
    "Azure Arc", "Azure Local", "Azure Stack HCI", "Azure VMware Solution", "Azure Migrate",
    "Azure Compute Gallery", "Azure Virtual Machine Scale Sets", "Azure CycleCloud",
    "Azure Batch", "Azure Monitor", "Azure Advisor", "Azure Policy", "Azure Blueprints",
    "Azure Automation", "Azure Backup", "Azure Site Recovery", "Azure Resource Manager",
    "Azure Bicep", "Bicep", "ARM templates", "Azure Verified Modules", "Deployment Stacks",
    "Microsoft Cost Management", "Azure Cost Management", "Azure savings plan",
    "Azure Files", "Azure File Sync", "Azure Blob Storage", "Azure Storage", "Azure NetApp Files",
    "Azure Elastic SAN", "Azure Storage Actions", "Azure Storage Discovery",
    "Azure SQL Database", "Azure SQL Managed Instance", "Azure SQL", "SQL Server",
    "Azure Cosmos DB", "Azure Database for PostgreSQL", "Azure Database for MySQL",
    "Azure DocumentDB", "Azure Databricks", "Microsoft Fabric", "Azure Synapse Analytics",
    "Azure Data Factory", "Azure Data Explorer", "Oracle Database@Azure", "Oracle AI Database@Azure",
    "Azure Virtual Network", "Azure Firewall", "Azure Front Door", "Azure ExpressRoute",
    "ExpressRoute", "Azure VPN Gateway", "Azure Application Gateway", "Azure Load Balancer",
    "Azure NAT Gateway", "NAT Gateway", "Azure DNS", "Azure Private Link", "Azure Virtual WAN",
    "Azure DDoS Protection", "Azure Bastion", "Network Security Perimeter",
    "Azure App Service", "Azure Functions", "Azure Container Apps", "Azure Container Registry",
    "Azure Container Instances", "Azure Red Hat OpenShift", "Azure Logic Apps", "Logic Apps",
    "Azure API Management", "API Management", "Azure Service Bus", "Service Bus",
    "Azure Event Hubs", "Azure Event Grid", "Azure Static Web Apps", "Azure DevOps",
    "GitHub Actions", "GitHub", "Azure Key Vault", "Key Vault", "Azure Cloud HSM",
    "Azure Managed HSM", "Microsoft Sentinel", "Microsoft Entra ID", "Microsoft Entra",
    "Azure confidential computing", "Confidential VMs", "Microsoft Sovereign Cloud",
    "Cloud Adoption Framework", "Azure Well-Architected Framework", "Azure Landing Zones",
    "Partner Center", "Microsoft Marketplace", "Azure Marketplace", "Azure portal", "Azure CLI",
    "Azure PowerShell", "Azure Maia", "Packer", "Terraform", "Kubernetes", "KEDA", "Traefik",
    "Linux", "Windows Server", "SAP on Azure", "SAP", "Microsoft Ignite", "Ignite",
    "Microsoft Learn", "Microsoft Azure", "Azure", "Microsoft", "MCP",
]
_SERVICES_SORTED = sorted(set(SERVICES), key=len, reverse=True)
_SERVICE_RE = re.compile(r"(?<![\w@])(" + "|".join(re.escape(s) for s in _SERVICES_SORTED) + r")(?![\w@])")
# Nomi troppo generici per essere mostrati come "servizio"
_GENERIC = {"Azure", "Microsoft", "Microsoft Azure", "Linux", "MCP", "Ignite", "Microsoft Ignite",
            "GitHub", "Kubernetes", "SAP", "Packer", "Terraform", "KEDA", "Traefik", "Bicep"}

CATEGORY_RULES = [
    ("Security", r"defender|sentinel|key vault|\bhsm\b|security|sovereign|sovranit|confidential|entra|"
                 r"compliance|zero trust|ddos|threat|encryption|firewall|identity"),
    ("AI", r"\bai\b|foundry|openai|copilot|\bagent|agentic|machine learning|\bllm|\bgpt|inference|"
           r"cognitive|ai search|maia"),
    ("Networking", r"network|vnet|expressroute|\bvpn|front door|load balancer|application gateway|"
                   r"\bdns\b|nat gateway|\bcidr|private link|private endpoint|virtual wan|\bcdn\b|bastion"),
    ("Data", r"\bsql\b|cosmos|database|databricks|fabric|storage|\bblob|azure files|file sync|backup|"
             r"postgres|mysql|synapse|data factory|\bdata\b|netapp|oracle|\bnas\b|documentdb|analytics"),
    ("Apps", r"kubernetes|\baks\b|container|app service|functions|logic apps|api management|service bus|"
             r"event grid|event hubs|devops|github|static web apps|\bapps?\b|serverless|integration"),
    ("Infrastructure", r"virtual machine|\bvms?\b|\barc\b|azure local|compute|migrat|monitor|\bhpc\b|"
                       r"cyclecloud|landing zone|governance|policy|finops|cost|reliab|resilien|hybrid"),
]
CATEGORIES = ["AI", "Infrastructure", "Security", "Networking", "Data", "Apps"]

# ---------------------------------------------------------------------------
# Contenuti curati (Microsoft Learn) - modificabili a mano
# ---------------------------------------------------------------------------
# Ritiri sempre in evidenza (verificati su Microsoft Learn / Azure Updates)
PINNED_RITIRI = [
    dict(date="dal 1 lug 2026", title="Reserved Instances non più acquistabili per le serie legacy",
         summary="Dal 1° luglio 2026 non è più possibile acquistare o rinnovare le Reserved VM Instances (RI): RI a 1 anno per Av2, Amv2, Bv1, D, Ds, Dv2, Dsv2, F, Fs, Fsv2, G, Gs, Ls, Lsv2; RI a 1 e 3 anni per Dv3, Dsv3, Ev3, Esv3. Le RI già attive valgono fino a scadenza; poi pay-as-you-go o Azure savings plan. Cina esclusa.",
         source="Microsoft Learn", link="https://learn.microsoft.com/en-us/azure/cost-management-billing/reservations/manage-legacy-vm-reservations-after-july-1-2026"),
    dict(date="da lug 2026", title="Limitazioni di capacità per le VM legacy (serie v2/v3/v4)",
         summary="Da luglio 2026 Azure applica limitazioni di capacità alle serie VM legacy: potrebbe non approvare nuove quote, nuovi deployment o espansioni per D/Ds/Dv2/Dsv2/Dv3/Dsv3/Dv4/Dsv4, Ev3/Esv3/Ev4/Esv4, F/Fs/Fsv2, Av2/Amv2, B/Bs, G/Gs, Ls/Lsv2. Le VM già in esecuzione non sono toccate. Migrazione a v5/v6/v7.",
         source="Microsoft Learn", link="https://learn.microsoft.com/en-us/azure/virtual-machines/migration/sizes/legacy-series-capacity-limitations"),
    dict(date="30 set 2026", title="VM NVv3-series e NVv4-series (GPU) in ritiro",
         summary="Il 30 settembre 2026 Azure ritira le VM GPU NVv3 (da NV12s_v3 a NV48s_v3) e NVv4. Migrare a NVadsA10_v5 (o NCasT4_v3 / NC_RTXPRO6000BSE_v6). Le RI per NVv3 sono già terminate.",
         source="Microsoft Learn", link="https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/lifecycle/retirement/nvv3-series-retirement"),
    dict(date="già ritirata · 30 set 2025", title="VM NCv3-series (GPU NVIDIA V100)",
         summary="Le VM NCv3 (da NC6s_v3 a NC24rs_v3) sono già ritirate e non più creabili. Migrazione consigliata: NVadsA10_v5 o NCasT4_v3.",
         source="Microsoft Learn", link="https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/lifecycle/retired-sizes-list"),
    dict(date="elenco ufficiale", title="Elenco completo VM Azure in ritiro",
         summary="Serie annunciate: D/Ds/Dv2/Dsv2 e Ls (1 mag 2028); Av2/Amv2, B v1, F/Fs/Fsv2, G/Gs, Lsv2 (15 nov 2028); M192_v2 (31 mar 2027); NP-series FPGA (31 mag 2027). Elenco sempre aggiornato su Microsoft Learn.",
         source="Microsoft Learn", link="https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/lifecycle/retired-sizes-list"),
    dict(date="30 set 2026", title="Runtime Python 2.7/3.8 e PowerShell 7.1/7.2 (Automation)",
         summary="Dal 1° ottobre 2026 i runtime Python 2.7, Python 3.8 e PowerShell 7.1/7.2 non sono più supportati in Azure Automation; i runbook restano attivi ma senza aggiornamenti di sicurezza.",
         source="Azure Updates", link=L_UPD),
    dict(date="entro 31 gen 2027", title="Migrazione da Azure Blueprints",
         summary="Microsoft invita a migrare da Azure Blueprints entro il 31 gennaio 2027, verso alternative supportate.",
         source="Azure Updates", link=L_UPD),
]

# Novità curate da Microsoft Learn ("What's new"): già in italiano.
# Escono automaticamente dalla pagina dopo MAX_AGE_DAYS.
CURATED_LEARN = [
    dict(src="Microsoft Learn", blog="Cloud Adoption Framework · What's new",
         url="https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/whats-new",
         date="2026-11-01", dateLabel="Novembre 2026", team="Documentazione Microsoft Learn",
         cat="Infrastructure", service="Cloud Adoption Framework",
         en="What's new in Microsoft's Cloud Adoption Framework – November 2026",
         it="Novità del Cloud Adoption Framework di Microsoft – novembre 2026",
         sum="Aggiornate le linee guida sulla strategia di adozione dell'AI e sulla piattaforma dati unificata. Rimossi gli articoli specifici per SAP, Oracle, Azure Arc e Azure Virtual Desktop; alcuni contenuti deprecati saranno eliminati da Microsoft Learn il 30 novembre 2026."),
    dict(src="Microsoft Learn", blog="Azure Files · What's new",
         url="https://learn.microsoft.com/en-us/azure/storage/files/files-whats-new",
         date="2026-11-01", dateLabel="4° trimestre 2026", team="Documentazione Microsoft Learn",
         status="Preview", cat="Data", service="Azure Files",
         en="In place provisioned v1 to provisioned v2 storage account upgrade is now in limited public preview",
         it="Aggiornamento diretto degli account di archiviazione da provisioned v1 a provisioned v2 in anteprima pubblica limitata",
         sum="È possibile aggiornare gli account provisioned v1 esistenti a provisioned v2 senza interruzioni, accedendo ai nuovi prezzi e funzionalità. Inoltre le file share con Microsoft.FileShares arrivano in 12 nuove regioni (51 in totale)."),
    dict(src="Microsoft Learn", blog="Azure Local · What's new (versione 2610)",
         url="https://learn.microsoft.com/en-us/azure/azure-local/whats-new?view=azloc-2610",
         date="2026-10-31", dateLabel="Ottobre 2026", team="Documentazione Microsoft Learn",
         status="GA", cat="Infrastructure", service="Azure Local",
         en="What's new in hyperconverged deployments of Azure Local – release 2610",
         it="Novità di Azure Local nelle distribuzioni iperconvergenti – versione 2610",
         sum="Disponibili a livello generale le Confidential VM con AMD SEV-SNP su Azure Local. In anteprima: Azure Arc gateway attivabile dopo il deployment, modifica delle impostazioni proxy e passaggio alla connettività su percorso privato."),
]

RESOURCES = [
    dict(tag="Partner", title="Annunci Microsoft Partner Center del mese",
         summary="Novità e annunci ufficiali per i partner Microsoft, rilevanti per il posizionamento CSP di Arrow.",
         source="Microsoft Learn — Partner Center", link=L_LEARN_PARTNER),
    dict(tag="GitHub", title="Azure su GitHub — organizzazione open source",
         summary="L'organizzazione ufficiale Azure su GitHub: SDK, documentazione, AKS, Bicep e Azure Landing Zones.",
         source="GitHub — Azure", link=L_GITHUB),
    dict(tag="GitHub", title="Azure Landing Zones",
         summary="Repository, moduli e pattern di deployment di Azure Landing Zones, mantenuti nell'organizzazione Azure su GitHub.",
         source="GitHub — Azure", link=L_GITHUB),
]

# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------
def log(*a):
    print(*a, flush=True)

def b64file(name):
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        log(f"ATTENZIONE: {name} non trovato, logo omesso")
        return ""
    with open(p, "rb") as f:
        return base64.b64encode(f.read()).decode()

def http_get(url, timeout=FETCH_TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/rss+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def strip_html(text):
    text = re.sub(r"(?is)<(script|style|figure|pre|code)[^>]*>.*?</\1>", " ", text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

def summarize(text, min_len=200, max_len=320):
    text = re.sub(r"^(introduction|overview|what'?s new\??|summary|tl;?dr:?)\s+", "", text, flags=re.I)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = ""
    for s in sentences:
        if not s:
            continue
        if len(out) + len(s) + 1 > max_len and out:
            break
        out = (out + " " + s).strip()
        if len(out) >= min_len:
            break
    if not out:
        out = text
    if len(out) > max_len:
        out = out[:max_len].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return out

def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        d = None
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                d = datetime.strptime(s, fmt)
                break
            except Exception:
                continue
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(TZ_ROME)

def canonical_url(u):
    try:
        p = urlsplit(u.strip())
        q = "&".join(sorted(x for x in p.query.split("&") if x and not x.lower().startswith(("utm_", "wt.", "ocid="))))
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), q, ""))
    except Exception:
        return (u or "").strip().lower()

def norm_title(t):
    t = re.sub(r"^\s*(\[[^\]]+\]\s*)+", "", t or "")
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()

NS = {"dc": "http://purl.org/dc/elements/1.1/",
      "content": "http://purl.org/rss/1.0/modules/content/",
      "atom": "http://www.w3.org/2005/Atom"}

def parse_feed(data):
    root = ET.fromstring(data)
    channel_title = ""
    ch = root.find("channel")
    if ch is not None and ch.find("title") is not None:
        channel_title = (ch.find("title").text or "").strip()
    items = []
    for it in root.iter("item"):
        def g(tag):
            e = it.find(tag, NS)
            return (e.text or "") if e is not None else ""
        cats = [(c.text or "").strip() for c in it.findall("category") if c.text]
        items.append(dict(title=g("title").strip(), link=g("link").strip(),
                          desc=g("description"), content=g("content:encoded"),
                          pub=g("pubDate") or g("dc:date"), author=g("dc:creator").strip(),
                          categories=cats))
    if not items:  # Atom
        for e in root.findall("atom:entry", NS):
            link = e.find("atom:link", NS)
            items.append(dict(title=(e.findtext("atom:title", "", NS)).strip(),
                              link=link.get("href", "") if link is not None else "",
                              desc=e.findtext("atom:summary", "", NS),
                              content=e.findtext("atom:content", "", NS),
                              pub=e.findtext("atom:updated", "", NS) or e.findtext("atom:published", "", NS),
                              author=(e.findtext("atom:author/atom:name", "", NS)).strip(),
                              categories=[]))
        channel_title = root.findtext("atom:title", "", NS) or channel_title
    return channel_title, items

def detect_status(text, categories=()):
    t = (text + " " + " ".join(categories)).lower()
    if re.search(r"retir|end of support|deprecat|will be removed", t):
        return "Ritiro"
    if re.search(r"\bpreview\b|in preview", t):
        return "Preview"
    if re.search(r"generally available|general availability|\bga\b|launched|now available", t):
        return "GA"
    return None

def clean_update_title(t):
    t = re.sub(r"^\s*(\[[^\]]+\]\s*)+", "", t)
    t = re.sub(r"^(generally available|general availability|public preview|private preview|"
               r"preview|retirement|launched|in development)\s*:\s*", "", t, flags=re.I)
    return t.strip()

def detect_service(title, text, categories=()):
    for cand in list(categories) + [title, text]:
        for m in _SERVICE_RE.finditer(cand or ""):
            name = m.group(1)
            if name not in _GENERIC:
                return {"AKS": "Azure Kubernetes Service"}.get(name, name)
    return "Microsoft Azure"

def detect_category(title, text, board=None):
    tl = title.lower()
    for cat, rx in CATEGORY_RULES:
        if re.search(rx, tl):
            return cat
    if board and board in BOARD_HINT:
        return BOARD_HINT[board]
    tx = text.lower()[:1500]
    scores = {cat: len(re.findall(rx, tx)) for cat, rx in CATEGORY_RULES}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Infrastructure"

def read_minutes(full_text):
    words = len(re.findall(r"\w+", full_text or ""))
    return max(1, round(words / 200)) if words >= 300 else None

def excluded(title):
    return any(re.search(p, title, re.I) for p in EXCLUDE_PATTERNS)

# ---------------------------------------------------------------------------
# Raccolta notizie
# ---------------------------------------------------------------------------
def make_item(src, blog, url, dt, author, title, full_text, categories=(), board=None, team=None):
    plain = strip_html(full_text)
    status = detect_status(title + " " + plain[:600], categories)
    if src == "Azure Updates":
        title = clean_update_title(title)
    item = dict(src=src, blog=blog, url=url, date=dt.strftime("%Y-%m-%d"),
                author=author or None, team=team, en=title, it=None,
                sumEn=summarize(plain), sum=None,
                cat=detect_category(title, plain, board),
                service=detect_service(title, plain, categories),
                status=status, translated=False)
    mins = read_minutes(plain)
    if mins and src != "Azure Updates":
        item["read"] = mins
        item["readEst"] = True
    return item

def collect_feed(url, src, blog_default, board=None, team=None, fetch=http_get):
    out = []
    try:
        ch_title, items = parse_feed(fetch(url))
    except Exception as e:
        log(f"  - feed non disponibile ({src} / {board or url}): {e}")
        return out
    blog = re.sub(r"\s+(articles|posts)$", "", ch_title or "", flags=re.I).strip() or blog_default
    cutoff = NOW - timedelta(days=MAX_AGE_DAYS)
    for it in items[:MAX_PER_FEED]:
        dt = parse_date(it["pub"])
        if not it["title"] or not it["link"] or dt is None or dt < cutoff:
            continue
        if excluded(it["title"]):
            continue
        full = it["content"] if len(it["content"]) > len(it["desc"]) else it["desc"]
        out.append(make_item(src, blog, it["link"], dt, it["author"], it["title"], full,
                             it["categories"], board, team))
    log(f"  - {src} / {blog}: {len(out)} notizie")
    return out

def collect_all(fetch=http_get):
    news = []
    log("Microsoft Community Hub (sezione Azure):")
    for b in HUB_BOARDS:
        news += collect_feed(HUB_RSS.format(b), "Microsoft Community Hub", b, board=b, fetch=fetch)
    log("Microsoft Azure Blog:")
    news += collect_feed(FEED_BLOG, "Microsoft Azure Blog", "Azure Blog", fetch=fetch)
    log("Azure Updates:")
    news += collect_feed(FEED_UPDATES, "Azure Updates", "Azure Updates", team="Azure Updates", fetch=fetch)
    cutoff = (NOW - timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%d")
    for c in CURATED_LEARN:
        if c["date"] >= cutoff:
            news.append(dict(c, translated=True, sumEn=None))
    return news

def dedupe(items):
    seen_url, seen_title, out = set(), set(), []
    # a parità di articolo vince la fonte più "ufficiale"/specifica
    prio = {"Microsoft Community Hub": 0, "Microsoft Azure Blog": 1, "Azure Updates": 2, "Microsoft Learn": 3}
    for it in sorted(items, key=lambda x: (prio.get(x["src"], 9), x["date"]), reverse=False):
        u, t = canonical_url(it["url"]), norm_title(it["en"])
        if u in seen_url or t in seen_title:
            continue
        seen_url.add(u); seen_title.add(t); out.append(it)
    removed = len(items) - len(out)
    if removed:
        log(f"Duplicati rimossi: {removed}")
    return out

# ---------------------------------------------------------------------------
# Traduzione (Azure AI Translator) con protezione dei nomi prodotto e cache
# ---------------------------------------------------------------------------
CACHE_FILE = os.path.join(HERE, "translations_cache.json")

def protect(text):
    esc = html.escape(text, quote=False)
    return _SERVICE_RE.sub(lambda m: f'<span class="notranslate">{m.group(1)}</span>', esc)

def unprotect(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text)).replace("  ", " ").strip()

def key_of(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()

def translate_batch(texts, key, region, endpoint):
    url = endpoint.rstrip("/") + "/translate?api-version=3.0&from=en&to=it&textType=html"
    body = json.dumps([{"Text": protect(t)} for t in texts]).encode("utf-8")
    headers = {"Ocp-Apim-Subscription-Key": key, "Content-Type": "application/json; charset=UTF-8"}
    if region:
        headers["Ocp-Apim-Subscription-Region"] = region
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=40) as r:
                res = json.loads(r.read().decode("utf-8"))
            return [unprotect(x["translations"][0]["text"]) for x in res]
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503) and attempt < 2:
                time.sleep(3 * (attempt + 1)); continue
            raise

def translate_items(items):
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    key = os.environ.get("AZURE_TRANSLATOR_KEY", "").strip()
    region = os.environ.get("AZURE_TRANSLATOR_REGION", "").strip()
    endpoint = os.environ.get("AZURE_TRANSLATOR_ENDPOINT", "https://api.cognitive.microsofttranslator.com").strip()

    todo = []
    for it in items:
        if it.get("translated"):
            continue
        for field in ("en", "sumEn"):
            t = it.get(field)
            if t and key_of(t) not in cache:
                todo.append(t)
    todo = list(dict.fromkeys(todo))
    if todo and not key:
        log(f"Traduzione: AZURE_TRANSLATOR_KEY non impostata, {len(todo)} testi restano in inglese")
    elif todo:
        log(f"Traduzione: {len(todo)} testi nuovi da tradurre")
        batch, size = [], 0
        def flush(b):
            if not b:
                return
            try:
                for src, dst in zip(b, translate_batch(b, key, region, endpoint)):
                    cache[key_of(src)] = dst
            except Exception as e:
                log(f"  - errore di traduzione (si riprova al prossimo giro): {e}")
        for t in todo:
            if len(batch) >= 50 or size + len(t) > 20000:
                flush(batch); batch, size = [], 0
            batch.append(t); size += len(t)
        flush(batch)

    used = {}
    for it in items:
        if it.get("translated"):
            continue
        ti = cache.get(key_of(it["en"])) if it.get("en") else None
        si = cache.get(key_of(it["sumEn"])) if it.get("sumEn") else None
        if ti:
            used[key_of(it["en"])] = ti
        if si:
            used[key_of(it["sumEn"])] = si
        it["it"] = ti or it["en"]
        it["sum"] = si or it.get("sumEn") or ""
        it["translated"] = bool(ti and si)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:   # tiene solo le voci ancora in uso
        json.dump(used, f, ensure_ascii=False, indent=0, sort_keys=True)

# ---------------------------------------------------------------------------
# Pagina HTML
# ---------------------------------------------------------------------------
def esc(s):
    return html.escape(s or "", quote=True)

def render_ritiri():
    out = []
    for c in PINNED_RITIRI:
        out.append(f'''        <li class="ritem">
          <span class="rdate">{esc(c["date"])}</span>
          <h3>{esc(c["title"])}</h3>
          <p>{esc(c["summary"])}</p>
          <a href="{esc(c["link"])}" target="_blank" rel="noopener noreferrer">Dettagli e guida di migrazione >><span class="sr-only"> (si apre in una nuova scheda)</span></a>
          <span class="rsrc">{esc(c["source"])}</span>
        </li>''')
    return "\n".join(out)

def render_resources():
    out = []
    for c in RESOURCES:
        out.append(f'''        <li class="res">
          <span class="tag">{esc(c["tag"])}</span>
          <h3>{esc(c["title"])}</h3>
          <p>{esc(c["summary"])}</p>
          <a href="{esc(c["link"])}" target="_blank" rel="noopener noreferrer">Apri fonte ufficiale >><span class="sr-only"> (si apre in una nuova scheda)</span></a>
        </li>''')
    return "\n".join(out)

def updated_label():
    return f"{NOW.day} {MESI[NOW.month-1]} {NOW.year}, ore {NOW:%H:%M}"

TEMPLATE = r'''<!DOCTYPE html>
<html lang="it" dir="ltr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="description" content="Le novità di Microsoft Azure: annunci, guide tecniche e aggiornamenti dai blog Microsoft e dai team di prodotto Azure.">
<title>Azure News Hub — Arrow Italia ECS</title>
<style>
:root{
  --bg:#000000;--surface:#0E0E0E;--surface-2:#161616;--ink:#FFFFFF;--muted:#B5B5B5;--line:#2E2E2E;--line-2:#3D3D3D;
  --azure:#FFFFFF;--link:#FFFFFF;--focus:#FFB900;
  --c-ai:#7E4FD6;--c-infrastructure:#0067B8;--c-security:#C4314B;--c-networking:#00788A;--c-data:#1E7A1E;--c-apps:#B4500E;
  --retire:#FF7A45;--radius:8px;
  font-family:"Segoe UI Variable Text","Segoe UI","Helvetica Neue",Arial,system-ui,sans-serif;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth;background:var(--bg)}
body{margin:0;background:var(--bg);color:var(--ink);font-size:16px;line-height:1.6;font-weight:400;-webkit-font-smoothing:antialiased}
a{color:var(--link)}
h1,h2,h3{font-weight:400;letter-spacing:-.005em}
:focus-visible{outline:3px solid var(--focus);outline-offset:2px;border-radius:4px}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.skip{position:absolute;inset-inline-start:12px;inset-block-start:-60px;background:var(--focus);color:#000;padding:10px 16px;border-radius:6px;font-weight:700;z-index:99;text-decoration:none}
.skip:focus{inset-block-start:12px}
.wrap{max-width:1180px;margin-inline:auto;padding-inline:24px}

/* Header in stile landing Eloqua: logo Arrow a sinistra, Microsoft a destra, filetto sottile */
.topbar{background:var(--bg);position:sticky;inset-block-start:0;z-index:30}
.topbar .wrap{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:96px;border-block-end:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:18px;text-decoration:none;color:var(--ink)}
.brand-logo{block-size:34px;inline-size:auto;display:block}
.brand-sep{inline-size:1px;block-size:30px;background:var(--line-2)}
.brand-text strong{display:block;font-size:1rem;font-weight:400;line-height:1.1}
.brand-text span{font-size:.74rem;color:var(--muted);letter-spacing:.06em;text-transform:uppercase}
.ms-logo{block-size:30px;inline-size:auto;display:block}
.it-flag{inline-size:24px;block-size:16px;border-radius:2px}
.proto-pill{display:none}

/* Hero: nero, titolo grande e leggero */
.hero{background:var(--bg);color:var(--ink)}
.hero .wrap{padding-block:72px 64px}
.eyebrow{font-size:.8rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin:0 0 14px}
.hero h1{font-size:clamp(2rem,3.8vw,2.75rem);line-height:1.15;margin:0 0 18px;font-weight:300}
.hero p.desc{max-inline-size:760px;margin:0;color:#E6E6E6;font-size:1.1rem;font-weight:300}
.hero-meta{display:flex;flex-wrap:wrap;gap:12px;margin-block-start:28px;align-items:center}
.meta-pill{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line-2);padding:6px 14px;border-radius:999px;font-size:.85rem;color:#E6E6E6}
.meta-pill .dot{inline-size:8px;block-size:8px;border-radius:50%;background:#6CCB5F}
.sources{display:flex;flex-wrap:wrap;gap:6px;margin:0;padding:0;list-style:none}
.sources li{border:1px solid var(--line-2);color:var(--muted);font-size:.76rem;padding:4px 10px;border-radius:4px}
.sources-line{font-size:.85rem;color:var(--muted)}
.banner{background:#1A1405;color:#F5DFA0;border-block-end:1px solid #4A3A10;font-size:.86rem}
.banner .wrap{padding-block:8px}

/* Barra di ricerca e filtri */
.toolbar{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:20px;margin-block:0 28px}
.toolbar-row{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:12px;align-items:end}
.field label{display:block;font-size:.8rem;color:var(--muted);margin-block-end:6px}
.search{position:relative}
.search svg{position:absolute;inset-inline-start:12px;inset-block-start:50%;transform:translateY(-50%);inline-size:18px;block-size:18px;fill:var(--muted)}
input[type=search],select{font:inherit;color:var(--ink);background:#000;border:1px solid var(--line-2);border-radius:6px;block-size:46px;padding-inline:12px;inline-size:100%;color-scheme:dark}
input[type=search]{padding-inline-start:40px}
input[type=search]::placeholder{color:#8A8A8A}
input[type=search]:focus,select:focus{border-color:#FFFFFF}
kbd{font-family:inherit;font-size:.72rem;border:1px solid var(--line-2);border-block-end-width:2px;border-radius:4px;padding:0 5px;color:var(--ink)}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-block-start:16px}
.chip{font:inherit;font-size:.88rem;color:var(--ink);background:transparent;border:1px solid var(--line-2);border-radius:6px;padding:7px 14px;cursor:pointer;display:inline-flex;align-items:center;gap:8px;min-block-size:40px}
.chip:hover{border-color:#FFFFFF}
.chip[aria-pressed=true]{background:#FFFFFF;border-color:#FFFFFF;color:#000}
.chip .sw{inline-size:10px;block-size:10px;border-radius:2px}
.chip .count{font-size:.75rem;opacity:.75}
.toolbar-foot{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px;margin-block-start:16px;padding-block-start:14px;border-block-start:1px solid var(--line)}
.check{display:inline-flex;align-items:center;gap:8px;font-size:.9rem;cursor:pointer}
.check input{inline-size:18px;block-size:18px;accent-color:#FFFFFF}
.status{font-size:.9rem;color:var(--muted)}
.status strong{color:var(--ink);font-weight:600}
.linkbtn{font:inherit;font-size:.85rem;font-weight:600;background:none;border:0;color:var(--ink);cursor:pointer;padding:6px 4px;text-decoration:underline}

/* Ritiri */
.ritiri{margin-block-end:28px;background:var(--surface);border:1px solid var(--line);border-inline-start:4px solid var(--retire);border-radius:var(--radius)}
.ritiri summary{cursor:pointer;padding:16px 20px;font-size:1.05rem;color:var(--ink)}
.ritiri summary span{color:var(--muted);font-size:.86rem;margin-inline-start:6px}
.ritiri-grid{list-style:none;margin:0;padding:0 20px 20px;display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.ritem{background:#000;border:1px solid var(--line);border-radius:6px;padding:14px;display:flex;flex-direction:column;gap:6px}
.rdate{align-self:flex-start;background:var(--retire);color:#000;font-size:.72rem;font-weight:700;padding:3px 9px;border-radius:4px}
.ritem h3{margin:0;font-size:1rem;line-height:1.3}
.ritem p{margin:0;font-size:.88rem;color:#D9D9D9;flex:1}
.ritem a{font-size:.85rem;font-weight:600}
.rsrc{font-size:.75rem;color:var(--muted)}

/* Card notizie */
main{padding-block-end:56px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:20px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);display:flex;flex-direction:column;overflow:hidden;transition:border-color .15s ease,transform .15s ease}
.card:hover{border-color:#5A5A5A;transform:translateY(-2px)}
.card-accent{block-size:3px;background:var(--cat)}
.card-body{padding:20px 22px 16px;display:flex;flex-direction:column;gap:10px;flex:1}
.card-top{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.badge{font-size:.7rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#fff;background:var(--cat);padding:3px 9px;border-radius:4px}
.tag{font-size:.74rem;color:#E6E6E6;background:transparent;border:1px solid var(--line-2);padding:2px 8px;border-radius:4px}
.tag.status-ga{color:#A8E6A0;border-color:#2F6B2F}
.tag.status-preview{color:#FFE08A;border-color:#6E5A1C}
.tag.status-ret{color:#FFB08F;border-color:#7A3A1E}
.tag.lang-en{color:var(--muted)}
.card h2{font-size:1.18rem;line-height:1.35;margin:4px 0 0}
.orig{font-size:.8rem;color:var(--muted);margin:0;font-style:italic}
.orig span{font-style:normal;font-weight:700;text-transform:uppercase;font-size:.66rem;letter-spacing:.06em;margin-inline-end:4px}
.summary{margin:0;font-size:.95rem;color:#E0E0E0;font-weight:300}
.service{font-size:.85rem;color:var(--muted);margin:0}
.service b{color:var(--ink);font-weight:600}
.meta{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:.82rem;color:var(--muted);margin:auto 0 0;padding:0;list-style:none}
.meta li{display:inline-flex;align-items:center;gap:6px}
.meta svg{inline-size:14px;block-size:14px;fill:currentColor;flex:none}
.role{font-size:.66rem;font-weight:700;padding:1px 6px;border-radius:3px;border:1px solid var(--line-2)}
.role.ms{color:#000;background:#fff;border-color:#fff}
.card-foot{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 22px;border-block-start:1px solid var(--line)}
.source{font-size:.8rem;color:var(--muted);line-height:1.3}
.source b{display:block;color:var(--ink);font-size:.84rem;font-weight:600}
/* Pulsante in stile Eloqua: bianco, testo nero, ">>" */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;font:inherit;font-size:.92rem;font-weight:400;color:#000;background:#FFFFFF;border:1px solid #FFFFFF;border-radius:6px;padding:10px 18px;text-decoration:none;white-space:nowrap;cursor:pointer;min-block-size:44px}
.btn:hover{background:#E6E6E6;border-color:#E6E6E6}
.btn svg{display:none}
.btn.ghost{background:transparent;color:#fff;border-color:#fff}
.btn.ghost:hover{background:#fff;color:#000}

/* Stati */
.skeleton .sk{background:linear-gradient(90deg,#161616 25%,#262626 50%,#161616 75%);background-size:200% 100%;animation:sh 1.2s infinite;border-radius:4px}
@keyframes sh{to{background-position:-200% 0}}
.state{background:var(--surface);border:1px dashed var(--line-2);border-radius:var(--radius);padding:56px 24px;text-align:center}
.state h2{margin:12px 0 6px;font-size:1.3rem}
.state p{margin:0 auto 20px;color:var(--muted);max-inline-size:520px}
.state .ico{inline-size:56px;block-size:56px;margin-inline:auto;border-radius:50%;display:grid;place-items:center;border:1px solid var(--line-2)}
.state .ico svg{inline-size:26px;block-size:26px;fill:#fff}
.state.error .ico svg{fill:#FF6B5A}
[hidden]{display:none !important}

/* Risorse e nota tecnica */
.resources{margin-block-start:48px}
.resources h2{font-size:1.5rem;margin:0 0 6px;font-weight:300}
.resources .lead{margin:0 0 18px;color:var(--muted)}
.res-grid{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
.res{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:18px 20px;display:flex;flex-direction:column;gap:6px}
.res h3{margin:4px 0 0;font-size:1.05rem}
.res p{margin:0;font-size:.9rem;color:#D9D9D9;flex:1}
.res a{font-size:.88rem;font-weight:600}
.res .tag{align-self:flex-start}
.note{margin-block-start:40px;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius)}
.note summary{cursor:pointer;padding:18px 20px;font-size:1.05rem}
.note .note-body{padding:0 20px 20px;font-size:.93rem;color:#E0E0E0}
.note h3{font-size:1rem;margin:18px 0 6px;color:#fff;font-weight:600}
.note ul{margin:0;padding-inline-start:20px}
.note code{color:#FFE08A}
.demo{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-block-start:18px;font-size:.88rem;color:var(--muted)}

/* Footer */
footer{background:var(--bg);color:#E6E6E6;border-block-start:1px solid var(--line);margin-block-start:56px}
.foot-main{padding-block:48px 28px}
.foot-brand{display:flex;align-items:center;gap:12px;margin-block-end:22px}
.foot-logo{block-size:28px;inline-size:auto;display:block}
.foot-brand-name{font-size:1.05rem;color:#fff;white-space:nowrap}
footer h2{color:#fff;margin:0 0 8px;font-size:1.6rem;font-weight:300}
.fsub{margin:0 0 26px;color:var(--muted);max-inline-size:640px}
.contacts{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}
.contact{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:18px 20px}
.c-role{margin:0 0 4px;font-size:.74rem;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}
.c-name{margin:0 0 10px;font-size:1.15rem;color:#fff}
.c-mail{display:inline-flex;align-items:center;gap:8px;color:#fff;font-size:.92rem;word-break:break-all}
.c-mail svg{inline-size:16px;block-size:16px;fill:currentColor;flex:none}
.foot-note{display:flex;flex-direction:column;gap:6px;border-block-start:1px solid var(--line);padding-block:18px 28px;font-size:.78rem;color:#8F8F8F;line-height:1.5}

@media (max-width:820px){
  .toolbar-row{grid-template-columns:1fr 1fr}
  .toolbar-row .search-field{grid-column:1 / -1}
  .grid{grid-template-columns:1fr}
  .topbar .wrap{min-height:72px}
  .brand-logo{block-size:26px}.ms-logo{block-size:22px}
  .hero .wrap{padding-block:48px 44px}
}
@media (max-width:480px){
  .wrap{padding-inline:16px}
  .toolbar-row{grid-template-columns:1fr}
  .card-foot{flex-direction:column;align-items:stretch}
  .brand-sep,.brand-text{display:none}
}
@media (prefers-reduced-motion: reduce){*{animation:none !important;transition:none !important;scroll-behavior:auto !important}}
@media print{.topbar,.toolbar,.ritiri,.note,.banner{display:none}html,body,footer{background:#fff;color:#000}.card{break-inside:avoid}}
</style>
<!-- Cloudflare Web Analytics --><script type='module' src='https://static.cloudflareinsights.com/beacon.min.js' data-cf-beacon='{"token": "6aaad914126a4039b9d9338deaff0d76"}'></script><!-- End Cloudflare Web Analytics -->
</head>
<body>
<a class="skip" href="#risultati">Vai alle notizie</a>

<header class="topbar">
  <div class="wrap">
    <a class="brand" href="#top" aria-label="Arrow Italia ECS · Azure News Hub — inizio pagina">
      __ARROW_IMG__
      <span class="brand-sep" aria-hidden="true"></span>
      <span class="brand-text"><strong>Azure News Hub</strong><span>Arrow Italia ECS</span></span>
    </a>
    <svg class="ms-logo" viewBox="0 0 132 30" role="img" aria-label="Microsoft"><rect x="0" y="2" width="12" height="12" fill="#fff"/><rect x="14" y="2" width="12" height="12" fill="#fff"/><rect x="0" y="16" width="12" height="12" fill="#fff"/><rect x="14" y="16" width="12" height="12" fill="#fff"/><text x="34" y="23" font-family="'Segoe UI',Arial,sans-serif" font-size="20" font-weight="600" fill="#fff">Microsoft</text></svg>
  </div>
</header>

<section class="hero" id="top" aria-labelledby="titolo">
  <div class="wrap">
    <p class="eyebrow">Microsoft Azure · Notizie e aggiornamenti</p>
    <h1 id="titolo">Le novità di Microsoft Azure</h1>
    <p class="desc">Annunci, guide tecniche e aggiornamenti di prodotto dai blog Microsoft e dai team di prodotto Azure.</p>
    <div class="hero-meta">
      <span class="meta-pill"><span class="dot" aria-hidden="true"></span>Ultimo aggiornamento: <time datetime="__UPDATED_ISO__">__UPDATED__</time></span>
      <ul class="sources" aria-label="Fonti ufficiali Microsoft">
        <li>Microsoft Community Hub</li><li>Azure Blog</li><li>Azure Updates</li><li>Microsoft Learn</li>
      </ul>
    </div>
  </div>
</section>

<main id="contenuto" class="wrap">
  <section class="toolbar" aria-label="Ricerca e filtri">
    <div class="toolbar-row">
      <div class="field search-field">
        <label for="q">Cerca nelle notizie <span class="sr-only">(scorciatoia: tasto barra)</span><span aria-hidden="true"> · premi <kbd>/</kbd></span></label>
        <div class="search">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 2a8 8 0 0 1 6.32 12.9l5.39 5.4-1.41 1.4-5.4-5.39A8 8 0 1 1 10 2Zm0 2a6 6 0 1 0 0 12 6 6 0 0 0 0-12Z"/></svg>
          <input type="search" id="q" placeholder="Es. AKS, Azure Arc, sovranità, backup…" autocomplete="off">
        </div>
      </div>
      <div class="field">
        <label for="fonte">Fonte</label>
        <select id="fonte"><option value="all">Tutte le fonti</option></select>
      </div>
      <div class="field">
        <label for="ordine">Ordina per data</label>
        <select id="ordine">
          <option value="desc">Più recenti prima</option>
          <option value="asc">Meno recenti prima</option>
        </select>
      </div>
    </div>
    <div class="chips" role="group" aria-label="Filtra per categoria" id="chips"></div>
    <div class="toolbar-foot">
      <span class="status" id="status" role="status" aria-live="polite"></span>
      <button type="button" class="linkbtn" id="reset">Azzera filtri</button>
    </div>
  </section>

  <details class="ritiri">
    <summary>⚠️ Ritiri Azure da tenere d'occhio <span>(__N_RITIRI__ avvisi · fonti: Microsoft Learn e Azure Updates)</span></summary>
    <ul class="ritiri-grid">
__RITIRI__
    </ul>
  </details>

  <section id="risultati" tabindex="-1" aria-label="Notizie">
    <div class="grid" id="grid" aria-busy="true"></div>
    <div class="state" id="empty" hidden>
      <div class="ico" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M10 2a8 8 0 0 1 6.32 12.9l5.39 5.4-1.41 1.4-5.4-5.39A8 8 0 1 1 10 2Zm0 2a6 6 0 1 0 0 12 6 6 0 0 0 0-12Z"/></svg></div>
      <h2>Nessuna notizia trovata</h2>
      <p>Nessun risultato corrisponde alla ricerca o ai filtri selezionati. Prova con un termine diverso o azzera i filtri.</p>
      <button type="button" class="btn ghost" id="reset2">Azzera filtri</button>
    </div>
    <div class="state error" id="error" role="alert" hidden>
      <div class="ico" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 2 1 21h22L12 2Zm0 4.5L19.5 19h-15L12 6.5ZM11 10v4h2v-4h-2Zm0 6v2h2v-2h-2Z"/></svg></div>
      <h2>Impossibile caricare le notizie</h2>
      <p>Si è verificato un problema nel caricamento dei contenuti. Riprova tra qualche istante.</p>
      <button type="button" class="btn" id="retry">Riprova</button>
    </div>
  </section>

  <section class="resources" aria-labelledby="risorse-titolo">
    <h2 id="risorse-titolo">Risorse per i partner</h2>
    <p class="lead">Annunci Partner Center e progetti open source ufficiali Azure.</p>
    <ul class="res-grid">
__RESOURCES__
    </ul>
  </section>
</main>

<footer aria-labelledby="contatti-titolo">
  <div class="wrap foot-main">
    <div class="foot-brand">
      __ARROW_IMG_FOOT__
      <svg class="it-flag" viewBox="0 0 3 2" role="img" aria-label="Italia"><rect width="1" height="2" x="0" fill="#009246"/><rect width="1" height="2" x="1" fill="#fff"/><rect width="1" height="2" x="2" fill="#CE2B37"/></svg>
      <span class="foot-brand-name">Arrow Italia ECS</span>
    </div>
    <h2 id="contatti-titolo">Hai bisogno di supporto? Contattaci</h2>
    <p class="fsub">Il team Cloud di Arrow Italia ECS è a disposizione per approfondimenti su Microsoft Azure, progetti CSP e percorsi di adozione cloud.</p>
    <ul class="contacts">
      <li class="contact"><p class="c-role">Microsoft Business Developer</p><p class="c-name">Marco Di Siero</p><a class="c-mail" href="mailto:Marco.DiSiero@arrow.com"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 5h18a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Zm1 2.4V17h16V7.4l-8 5.3-8-5.3ZM5.6 7 12 11.3 18.4 7H5.6Z"/></svg>Marco.DiSiero@arrow.com</a></li>
      <li class="contact"><p class="c-role">Brand Manager Azure</p><p class="c-name">Giuseppe Cirillo</p><a class="c-mail" href="mailto:Giuseppe.Cirillo@arrow.com"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 5h18a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Zm1 2.4V17h16V7.4l-8 5.3-8-5.3ZM5.6 7 12 11.3 18.4 7H5.6Z"/></svg>Giuseppe.Cirillo@arrow.com</a></li>
      <li class="contact"><p class="c-role">Technical Sales Engineer</p><p class="c-name">Gianluca Arria</p><a class="c-mail" href="mailto:Gianluca.Arria@arrow.com"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 5h18a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Zm1 2.4V17h16V7.4l-8 5.3-8-5.3ZM5.6 7 12 11.3 18.4 7H5.6Z"/></svg>Gianluca.Arria@arrow.com</a></li>
    </ul>
  </div>
  <div class="wrap foot-note">
    <span>Le notizie provengono da fonti ufficiali Microsoft: Microsoft Community Hub (sezione Azure), Microsoft Azure Blog, Azure Updates e Microsoft Learn. Titoli e sintesi sono tradotti automaticamente in italiano; per il testo completo fa fede l'articolo originale. Pagina aggiornata automaticamente al __UPDATED__.</span>
    <span>Arrow e il logo Arrow sono marchi registrati di Arrow Electronics, Inc. Microsoft, Azure e il logo Microsoft sono marchi del gruppo Microsoft. I contenuti originali restano © Microsoft e dei rispettivi autori.</span>
  </div>
</footer>

<script type="application/json" id="news-data">__NEWS_JSON__</script>
<script>
(function(){
  "use strict";
  var CATS=["AI","Infrastructure","Security","Networking","Data","Apps"];
  var SOURCES=["Microsoft Community Hub","Microsoft Azure Blog","Azure Updates","Microsoft Learn"];
  var $=function(id){return document.getElementById(id);};
  var grid=$("grid"),statusEl=$("status"),emptyEl=$("empty"),errorEl=$("error");
  var state={q:"",cat:"all",src:"all",order:"desc"};
  var DATA=[];
  var fmt=new Intl.DateTimeFormat("it-IT",{day:"numeric",month:"long",year:"numeric"});
  function norm(s){return (s||"").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"").replace(/[^a-z0-9@]+/g," ").trim();}
  function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e;}
  function svg(path){var s=document.createElementNS("http://www.w3.org/2000/svg","svg");s.setAttribute("viewBox","0 0 24 24");s.setAttribute("aria-hidden","true");var p=document.createElementNS("http://www.w3.org/2000/svg","path");p.setAttribute("d",path);s.appendChild(p);return s;}
  var ICON={cal:"M7 2v2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2V2h-2v2H9V2H7Zm12 8v10H5V10h14Z",
    user:"M12 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10Zm0 2c-4.4 0-8 2.2-8 5v3h16v-3c0-2.8-3.6-5-8-5Z",
    clock:"M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm1 5h-2v6l5 3 1-1.7-4-2.3V7Z",
    ext:"M14 3h7v7h-2V6.4l-9.3 9.3-1.4-1.4L17.6 5H14V3ZM5 5h6v2H7v10h10v-4h2v6H5V5Z"};
  function metaItem(icon,content){var li=el("li");li.appendChild(svg(ICON[icon]));if(typeof content==="string")li.appendChild(document.createTextNode(content));else li.appendChild(content);return li;}
  function card(n){
    var a=el("article","card");a.style.setProperty("--cat","var(--c-"+n.cat.toLowerCase()+")");a.setAttribute("aria-labelledby","t-"+n.id);
    a.appendChild(el("div","card-accent"));
    var b=el("div","card-body"),top=el("div","card-top");
    top.appendChild(el("span","badge",n.cat));
    if(n.status==="GA")top.appendChild(el("span","tag status-ga","Disponibile (GA)"));
    if(n.status==="Preview")top.appendChild(el("span","tag status-preview","Anteprima"));
    if(n.status==="Ritiro")top.appendChild(el("span","tag status-ret","Ritiro"));
    if(!n.translated)top.appendChild(el("span","tag lang-en","Non tradotto"));
    b.appendChild(top);
    var h=el("h2",null,n.it||n.en);h.id="t-"+n.id;if(!n.translated)h.lang="en";b.appendChild(h);
    if(n.translated&&n.en&&n.en!==n.it){var o=el("p","orig");o.lang="en";var os=el("span",null,"Originale");os.lang="it";o.appendChild(os);o.appendChild(document.createTextNode(n.en));b.appendChild(o);}
    if(n.sum){var sp=el("p","summary",n.sum);if(!n.translated)sp.lang="en";b.appendChild(sp);}
    var sv=el("p","service");sv.appendChild(document.createTextNode("Servizio: "));sv.appendChild(el("b",null,n.service));b.appendChild(sv);
    var m=el("ul","meta");m.setAttribute("aria-label","Dettagli");
    var t=el("time",null,n.dateLabel||fmt.format(new Date(n.date+"T12:00:00")));t.dateTime=n.date;m.appendChild(metaItem("cal",t));
    m.appendChild(metaItem("user",n.author||n.team||n.src));
    if(n.read)m.appendChild(metaItem("clock",(n.readEst?"~":"")+n.read+" min di lettura"+(n.readEst?" (stima)":"")));
    b.appendChild(m);a.appendChild(b);
    var f=el("div","card-foot"),s=el("div","source");
    s.appendChild(el("b",null,n.src));s.appendChild(document.createTextNode(n.blog||""));f.appendChild(s);
    var l=el("a","btn");l.href=n.url;l.target="_blank";l.rel="noopener noreferrer";l.hreflang="en";
    l.appendChild(document.createTextNode("Leggi l’articolo originale >>"));
    l.setAttribute("aria-label","Leggi l’articolo originale (in inglese, si apre in una nuova scheda): "+n.en);
    f.appendChild(l);a.appendChild(f);return a;
  }
  function filtered(){
    var q=norm(state.q);
    return DATA.filter(function(n){
      if(state.cat!=="all"&&n.cat!==state.cat)return false;
      if(state.src!=="all"&&n.src!==state.src)return false;
      if(q){var hay=norm([n.it,n.en,n.sum,n.sumEn,n.service,n.author,n.cat,n.blog,n.src].join(" "));
        return q.split(" ").every(function(w){return hay.indexOf(w)>-1;});}
      return true;
    }).sort(function(x,y){return state.order==="desc"?y.date.localeCompare(x.date):x.date.localeCompare(y.date);});
  }
  function render(){
    var list=filtered();grid.textContent="";
    list.forEach(function(n){grid.appendChild(card(n));});
    grid.setAttribute("aria-busy","false");errorEl.hidden=true;
    emptyEl.hidden=list.length>0;grid.hidden=list.length===0;
    statusEl.textContent="";statusEl.appendChild(el("strong",null,list.length===1?"1 notizia":list.length+" notizie"));
    statusEl.appendChild(document.createTextNode(" su "+DATA.length));
  }
  function buildChips(){
    var box=$("chips");box.textContent="";
    [{id:"all",label:"Tutte"}].concat(CATS.map(function(c){return {id:c,label:c};})).forEach(function(c){
      var b=el("button","chip");b.type="button";b.dataset.cat=c.id;b.setAttribute("aria-pressed",String(state.cat===c.id));
      if(c.id!=="all"){var sw=el("span","sw");sw.style.background="var(--c-"+c.id.toLowerCase()+")";sw.setAttribute("aria-hidden","true");b.appendChild(sw);}
      b.appendChild(document.createTextNode(c.label+" "));
      var n=DATA.filter(function(x){return c.id==="all"||x.cat===c.id;}).length;
      var ct=el("span","count","("+n+")");ct.setAttribute("aria-label",n+" notizie");b.appendChild(ct);
      b.addEventListener("click",function(){state.cat=c.id;box.querySelectorAll(".chip").forEach(function(x){x.setAttribute("aria-pressed",String(x.dataset.cat===c.id));});render();});
      box.appendChild(b);
    });
  }
  function buildSources(){
    var sel=$("fonte"),srcs={};SOURCES.forEach(function(s){srcs[s]=1;});DATA.forEach(function(n){srcs[n.src]=1;});
    Object.keys(srcs).forEach(function(s){var o=el("option",null,s);o.value=s;sel.appendChild(o);});
  }
  function showLoading(){
    for(var i=0;i<6;i++){var c=el("div","card skeleton");c.setAttribute("aria-hidden","true");var b=el("div","card-body");
      [["20%",18],["90%",22],["70%",22],["100%",14],["95%",14],["60%",14]].forEach(function(d){var s=el("div","sk");s.style.inlineSize=d[0];s.style.blockSize=d[1]+"px";b.appendChild(s);});
      c.appendChild(b);grid.appendChild(c);}
    statusEl.textContent="Caricamento delle notizie in corso…";
  }
  function showError(){grid.hidden=true;emptyEl.hidden=true;errorEl.hidden=false;grid.setAttribute("aria-busy","false");statusEl.textContent="Errore nel caricamento";}
  function reset(){state={q:"",cat:"all",src:"all",order:"desc"};$("q").value="";$("fonte").value="all";$("ordine").value="desc";
    document.querySelectorAll(".chip").forEach(function(x){x.setAttribute("aria-pressed",String(x.dataset.cat==="all"));});render();$("q").focus();}
  var deb;
  $("q").addEventListener("input",function(e){clearTimeout(deb);deb=setTimeout(function(){state.q=e.target.value;render();},150);});
  $("fonte").addEventListener("change",function(e){state.src=e.target.value;render();});
  $("ordine").addEventListener("change",function(e){state.order=e.target.value;render();});
  $("reset").addEventListener("click",reset);$("reset2").addEventListener("click",reset);
  $("retry").addEventListener("click",function(){location.reload();});
  document.addEventListener("keydown",function(e){var tag=(e.target.tagName||"").toLowerCase();
    if(e.key==="/"&&tag!=="input"&&tag!=="select"&&tag!=="textarea"){e.preventDefault();$("q").focus();}
    if(e.key==="Escape"&&e.target.id==="q"&&e.target.value){e.target.value="";state.q="";render();}});
  showLoading();
  try{
    DATA=JSON.parse($("news-data").textContent).map(function(n,i){n.id=i;return n;});
    if(!DATA.length)throw new Error("vuoto");
    buildChips();buildSources();render();
  }catch(err){showError();}
})();
</script>
</body>
</html>'''

def render_page(items):
    white = b64file("arrow_white.png")
    img = (f'<img class="brand-logo" src="data:image/png;base64,{white}" alt="Arrow">' if white
           else '<strong>ARROW</strong>')
    img_foot = (f'<img class="foot-logo" src="data:image/png;base64,{white}" alt="Arrow">' if white else "")
    data = json.dumps(items, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return (TEMPLATE
            .replace("__ARROW_IMG_FOOT__", img_foot)
            .replace("__ARROW_IMG__", img)
            .replace("__UPDATED_ISO__", NOW.isoformat(timespec="minutes"))
            .replace("__UPDATED__", updated_label())
            .replace("__N_RITIRI__", str(len(PINNED_RITIRI)))
            .replace("__RITIRI__", render_ritiri())
            .replace("__RESOURCES__", render_resources())
            .replace("__NEWS_JSON__", data))

# ---------------------------------------------------------------------------
def main(fetch=http_get):
    log(f"Azure News Hub - build {updated_label()}")
    raw = collect_all(fetch)
    if not any(it["src"] != "Microsoft Learn" or not it.get("translated") for it in raw):
        log("ERRORE: nessun feed ha risposto. index.html NON viene sovrascritto (resta la versione precedente).")
        sys.exit(1)
    items = dedupe(raw)
    items.sort(key=lambda x: x["date"], reverse=True)
    items = items[:MAX_ITEMS]
    translate_items(items)
    page = render_page(items)
    with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    with open(os.path.join(HERE, "news.json"), "w", encoding="utf-8") as f:
        json.dump(dict(updated=NOW.isoformat(timespec="minutes"), items=items), f, ensure_ascii=False, indent=1)
    by_src = {}
    for it in items:
        by_src[it["src"]] = by_src.get(it["src"], 0) + 1
    log(f"index.html generato: {len(items)} notizie {by_src} - {len(page)} byte")

if __name__ == "__main__":
    main()
