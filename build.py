#!/usr/bin/env python3
# Azure News Hub - build script (GitHub Actions ready).
# Legge i feed ufficiali Microsoft Azure e ricostruisce index.html.
# Nessuna dipendenza esterna: usa solo la libreria standard di Python.
import base64, html, os, re, urllib.request
from datetime import datetime
import xml.etree.ElementTree as ET
try:
    from zoneinfo import ZoneInfo
    NOW = datetime.now(ZoneInfo("Europe/Rome"))
except Exception:
    NOW = datetime.now()

HERE = os.path.dirname(os.path.abspath(__file__))
MESI = ["gennaio","febbraio","marzo","aprile","maggio","giugno","luglio",
        "agosto","settembre","ottobre","novembre","dicembre"]
MESI_ABBR = ["gen","feb","mar","apr","mag","giu","lug","ago","set","ott","nov","dic"]
TZ = NOW.tzname() or "CEST"
UPDATED = f"{NOW.day} {MESI[NOW.month-1]} {NOW.year}, ore {NOW:%H:%M} ({TZ})"

def b64(name):
    with open(os.path.join(HERE, name), "rb") as f:
        return base64.b64encode(f.read()).decode()

arrow_black = b64("arrow_black.png")
arrow_white = b64("arrow_white.png")

# --- Fonti ufficiali (RSS) ---
FEED_UPDATES = "https://www.microsoft.com/releasecommunications/api/v2/azure/rss"
FEED_BLOG    = "https://azure.microsoft.com/en-us/blog/feed/"
L_UPD    = "https://azure.microsoft.com/en-us/updates/"
L_BLOG   = "https://azure.microsoft.com/en-us/blog/"
L_GITHUB = "https://github.com/Azure"
L_LEARN  = "https://learn.microsoft.com/en-us/partner-center/announcements/2026-july"

def card(tag, tag_class, date, title, summary, source, link):
    return dict(tag=tag, tag_class=tag_class, date=date, title=title,
                summary=summary, source=source, link=link)

def fmt_date(pubdate):
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            d = datetime.strptime(pubdate.strip(), fmt)
            return f"{d.day} {MESI_ABBR[d.month-1]} {d.year}"
        except Exception:
            continue
    return ""

def clean(text, limit=240):
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip() + ("…" if len(text) > limit else "")

def fetch_rss(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "AzureNewsHub/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    root = ET.fromstring(data)
    items = []
    for it in root.iter("item"):
        def g(tag):
            e = it.find(tag)
            return e.text if e is not None and e.text else ""
        items.append(dict(title=g("title"), link=g("link"),
                           desc=g("description"), pub=g("pubDate")))
    return items

def classify(title, desc):
    t = (title + " " + desc).lower()
    if "retir" in t or "end of support" in t or "deprecat" in t:
        return ("Ritiro", "t-ret")
    if "preview" in t:
        return ("Preview", "t-prev")
    if "generally available" in t or "general availability" in t or "now available" in t or " ga " in t:
        return ("GA", "t-ga")
    return (None, None)

# --- Ritiri "pinned": sempre in evidenza (verificati su Microsoft Learn) ---
pinned_ritiri = [
    card("Ritiro","t-ret","dal 1 lug 2026","Reserved Instances non più acquistabili per le serie legacy",
         "Dal 1° luglio 2026 non è più possibile acquistare o rinnovare le Reserved VM Instances (RI): RI a 1 anno per Av2, Amv2, Bv1, D, Ds, Dv2, Dsv2, F, Fs, Fsv2, G, Gs, Ls, Lsv2; RI a 1 e 3 anni per Dv3, Dsv3, Ev3, Esv3. Le RI già attive valgono fino a scadenza; poi pay-as-you-go o Azure savings plan. Cina esclusa.",
         "Microsoft Learn","https://learn.microsoft.com/en-us/azure/cost-management-billing/reservations/manage-legacy-vm-reservations-after-july-1-2026"),
    card("Ritiro","t-ret","da lug 2026","Limitazioni di capacità per le VM legacy (serie v2/v3/v4)",
         "Da luglio 2026 Azure applica limitazioni di capacità alle serie VM legacy: potrebbe non approvare nuove quote, nuovi deployment o espansioni per D/Ds/Dv2/Dsv2/Dv3/Dsv3/Dv4/Dsv4, Ev3/Esv3/Ev4/Esv4, F/Fs/Fsv2, Av2/Amv2, B/Bs, G/Gs, Ls/Lsv2. Le VM già in esecuzione non sono toccate. Migrazione a v5/v6/v7; le serie v1 e v2 sono annunciate per il ritiro.",
         "Microsoft Learn","https://learn.microsoft.com/en-us/azure/virtual-machines/migration/sizes/legacy-series-capacity-limitations"),
    card("Ritiro","t-ret","30 set 2026","VM NVv3-series e NVv4-series (GPU) in ritiro",
         "Il 30 settembre 2026 Azure ritira le VM GPU NVv3 (da NV12s_v3 a NV48s_v3) e NVv4. Migrare a NVadsA10_v5 (o NCasT4_v3 / NC_RTXPRO6000BSE_v6). Le RI per NVv3 sono già terminate.",
         "Microsoft Learn","https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/lifecycle/retirement/nvv3-series-retirement"),
    card("Ritiro","t-ret","già ritirata · 30 set 2025","VM NCv3-series (GPU NVIDIA V100)",
         "Le VM NCv3 (da NC6s_v3 a NC24rs_v3) sono già ritirate e non più creabili. Migrazione consigliata: NVadsA10_v5 o NCasT4_v3.",
         "Microsoft Learn","https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/lifecycle/retired-sizes-list"),
    card("Ritiro","t-ret","elenco ufficiale","Elenco completo VM Azure in ritiro",
         "Serie annunciate: D/Ds/Dv2/Dsv2 e Ls (1 mag 2028); Av2/Amv2, B v1, F/Fs/Fsv2, G/Gs, Lsv2 (15 nov 2028); M192_v2 (31 mar 2027); NP-series FPGA (31 mag 2027). Elenco sempre aggiornato su Microsoft Learn.",
         "Microsoft Learn","https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/lifecycle/retired-sizes-list"),
    card("Ritiro","t-ret","30 set 2026","Runtime Python 2.7/3.8 e PowerShell 7.1/7.2 (Automation)",
         "Dal 1° ottobre 2026 i runtime Python 2.7, Python 3.8 e PowerShell 7.1/7.2 non saranno più supportati in Azure Automation; i runbook restano attivi ma senza aggiornamenti di sicurezza.",
         "Azure Updates", L_UPD),
    card("Ritiro","t-ret","entro 31 gen 2027","Migrazione da Azure Blueprints",
         "Microsoft invita a migrare da Azure Blueprints entro il 31 gennaio 2027, verso alternative supportate.",
         "Azure Updates", L_UPD),
]

# --- Contenuti curati (partner + github) ---
partner = [
    card("Partner","t-partner","2026","Azure IP co-sell e Marketplace-first (FY27)",
         "In FY27 il Microsoft Marketplace diventa il percorso primario per il co-sell su scala. Rilevante per il posizionamento CSP di Arrow.",
         "Microsoft Learn — Partner Center", L_LEARN),
]
github = [
    card("GitHub","t-gh","ufficiale","Azure su GitHub — organizzazione open source",
         "L'organizzazione ufficiale Azure su GitHub: SDK, documentazione, AKS, Bicep e Azure Landing Zones.",
         "GitHub — Azure", L_GITHUB),
    card("GitHub","t-gh","ufficiale","Azure Landing Zones",
         "Repository, moduli e pattern di deployment di Azure Landing Zones, mantenuti nell'organizzazione Azure su GitHub.",
         "GitHub — Azure", L_GITHUB),
]

# --- Fallback se i feed non rispondono ---
fallback_updates = [
    card("GA","t-ga","2026","Network Security Perimeter per Azure Event Hubs",
         "Il supporto al Network Security Perimeter per Azure Event Hubs è generalmente disponibile.",
         "Azure Updates", L_UPD),
]
fallback_blog = [
    card("Blog","t-blog","2026","Microsoft Foundry per l'era agentica",
         "Aggiornamenti dal blog ufficiale Microsoft Azure.",
         "Microsoft Azure Blog", L_BLOG),
]

# --- Costruzione liste da feed (con fallback) ---
updates_ga, updates_prev, updates_ret, blog = [], [], [], []
try:
    for it in fetch_rss(FEED_UPDATES)[:60]:
        tag, cls = classify(it["title"], it["desc"])
        if not tag:
            continue
        c = card(tag, cls, fmt_date(it["pub"]), clean(it["title"], 120),
                 clean(it["desc"], 240), "Azure Updates", it["link"] or L_UPD)
        if tag == "GA" and len(updates_ga) < 12: updates_ga.append(c)
        elif tag == "Preview" and len(updates_prev) < 10: updates_prev.append(c)
        elif tag == "Ritiro" and len(updates_ret) < 8: updates_ret.append(c)
except Exception as e:
    print("Feed updates non disponibile:", e)
    updates_ga = fallback_updates

try:
    for it in fetch_rss(FEED_BLOG)[:10]:
        blog.append(card("Blog","t-blog", fmt_date(it["pub"]), clean(it["title"],120),
                         clean(it["desc"],240), "Microsoft Azure Blog", it["link"] or L_BLOG))
except Exception as e:
    print("Feed blog non disponibile:", e)
    blog = fallback_blog

if not blog:
    blog = fallback_blog
if not (updates_ga or updates_prev):
    updates_ga = fallback_updates

# Ritiri = pinned + eventuali ritiri dal feed (dedup per titolo)
seen = {c["title"].lower() for c in pinned_ritiri}
extra_ret = [c for c in updates_ret if c["title"].lower() not in seen]
ritiri = pinned_ritiri + extra_ret
updates_grid = updates_ga + updates_prev + ritiri

MS_LOGO = '''<svg class="ms-logo" viewBox="0 0 118 24" role="img" aria-label="Microsoft">
  <rect x="0" y="0" width="11" height="11" fill="#F25022"/>
  <rect x="12.5" y="0" width="11" height="11" fill="#7FBA00"/>
  <rect x="0" y="12.5" width="11" height="11" fill="#00A4EF"/>
  <rect x="12.5" y="12.5" width="11" height="11" fill="#FFB900"/>
  <text x="30" y="17" font-family="'Segoe UI',Arial,sans-serif" font-size="16" font-weight="600" fill="#5E5E5E">Microsoft</text>
</svg>'''

def render_cards(items):
    catmap = {'t-ga':'ga','t-prev':'preview','t-ret':'ritiro','t-blog':'blog','t-partner':'partner','t-gh':'github'}
    out = []
    for c in items:
        cat = catmap.get(c['tag_class'], 'all')
        out.append(f'''      <article class="card" data-cat="{cat}">
        <div class="card-top">
          <span class="tag {c['tag_class']}">{html.escape(c['tag'])}</span>
          <span class="date">{html.escape(c['date'])}</span>
        </div>
        <h3>{html.escape(c['title'])}</h3>
        <p>{html.escape(c['summary'])}</p>
        <div class="card-foot">
          <span class="src">{html.escape(c['source'])}</span>
          <a href="{html.escape(c['link'])}" target="_blank" rel="noopener">Apri fonte ufficiale →</a>
        </div>
      </article>''')
    return "\n".join(out)

def render_highlight(items):
    out = []
    for c in items:
        out.append(f'''      <div class="ritem">
        <span class="rdate">{html.escape(c['date'])}</span>
        <h4>{html.escape(c['title'])}</h4>
        <p>{html.escape(c['summary'])}</p>
        <a href="{html.escape(c['link'])}" target="_blank" rel="noopener">Dettagli e guida di migrazione →</a>
      </div>''')
    return "\n".join(out)

HTML = '''<!DOCTYPE html>
<html lang="it" dir="ltr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Azure News Hub — Arrow ECS</title>
<style>
:root{--azure:#0078D4;--azure-dark:#004E8C;--azure-deep:#003057;--bg:#f3f6fb;--surface:#fff;--ink:#1b1f27;--muted:#5b6472;--border:#e2e8f2;--shadow:0 2px 10px rgba(0,48,87,.08)}
*{box-sizing:border-box}html,body{margin:0;padding:0}
body{font-family:'Segoe UI',Roboto,Arial,sans-serif;background:var(--bg);color:var(--ink);line-height:1.55}
a{color:var(--azure);text-decoration:none}a:hover{text-decoration:underline}
.topbar{position:sticky;top:0;z-index:20;background:var(--surface);border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 28px;flex-wrap:wrap}
.topbar .arrow{height:26px;width:auto;display:block}
.topbar .brand-right{display:flex;align-items:center;gap:14px}
.ms-logo{height:24px;width:auto;display:block}.divider{width:1px;height:26px;background:var(--border)}
.brand-tag{font-size:.82rem;color:var(--muted);font-weight:600;letter-spacing:.02em}
.hero{background:linear-gradient(135deg,var(--azure-deep) 0%,var(--azure-dark) 45%,var(--azure) 100%);color:#fff;padding:52px 28px 46px;text-align:center}
.hero h1{margin:0 0 10px;font-size:2.15rem;font-weight:700}
.hero p.sub{margin:0 auto;max-width:720px;font-size:1.05rem;color:#dbeafe}
.updated{display:inline-block;margin-top:18px;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.28);color:#fff;padding:6px 14px;border-radius:999px;font-size:.82rem;font-weight:600}
.sources{display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin-top:20px}
.sources span{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.22);color:#eaf3ff;font-size:.76rem;padding:5px 11px;border-radius:6px;font-weight:600}
.filterbar{max-width:1120px;margin:24px auto 0;padding:0 28px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;justify-content:center}
.filterbar .flabel{font-size:.82rem;color:var(--muted);font-weight:700;margin-inline-end:4px}
.chip{cursor:pointer;font-family:inherit;font-size:.82rem;font-weight:600;color:var(--ink);background:var(--surface);border:1px solid var(--border);border-radius:999px;padding:7px 14px;display:inline-flex;align-items:center;gap:7px;transition:all .12s ease}
.chip:hover{border-color:var(--azure);color:var(--azure)}
.chip .cdot{width:9px;height:9px;border-radius:3px;display:inline-block}
.chip.active{color:#fff;border-color:transparent}
.chip[data-filter="all"].active{background:var(--azure)}.chip[data-filter="ga"].active{background:#107C10}.chip[data-filter="preview"].active{background:#8661C5}.chip[data-filter="ritiro"].active{background:#D83B01}.chip[data-filter="blog"].active{background:#0078D4}.chip[data-filter="partner"].active{background:#008272}.chip[data-filter="github"].active{background:#24292F}
.chip.active .cdot{background:#fff !important}.card.hidden,.section.hidden{display:none}
.ritiri{max-width:1120px;margin:26px auto 0;padding:0 28px}
.ritiri-box{background:var(--surface);border:1px solid var(--border);border-left:5px solid #D83B01;border-radius:12px;padding:18px 20px 16px;box-shadow:var(--shadow)}
.ritiri-box h2{margin:0 0 4px;font-size:1.22rem;color:#D83B01;display:flex;align-items:center;gap:9px}
.ritiri-box .lead{margin:0 0 14px;color:var(--muted);font-size:.88rem}
.ritiri-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px}
.ritem{background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:13px 14px;display:flex;flex-direction:column}
.ritem .rdate{align-self:flex-start;background:#D83B01;color:#fff;font-size:.72rem;font-weight:700;padding:3px 9px;border-radius:6px;margin-bottom:8px}
.ritem h4{margin:0 0 6px;font-size:.97rem;line-height:1.3}
.ritem p{margin:0 0 10px;font-size:.85rem;color:var(--ink);opacity:.85;flex:1}.ritem a{font-size:.8rem;font-weight:600}
main{max-width:1120px;margin:0 auto;padding:10px 28px 40px}.section{margin-top:38px}
.section h2{font-size:1.35rem;margin:0 0 4px;display:flex;align-items:center;gap:10px}
.section .lead{margin:0 0 18px;color:var(--muted);font-size:.95rem}
.bar{width:4px;height:22px;border-radius:3px;background:var(--azure);display:inline-block}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px 18px 14px;box-shadow:var(--shadow);display:flex;flex-direction:column;transition:transform .12s ease,box-shadow .12s ease}
.card:hover{transform:translateY(-3px);box-shadow:0 8px 22px rgba(0,48,87,.14)}
.card-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
.tag{font-size:.72rem;font-weight:700;letter-spacing:.03em;text-transform:uppercase;color:#fff;padding:3px 9px;border-radius:6px}
.t-ga{background:#107C10}.t-prev{background:#8661C5}.t-ret{background:#D83B01}.t-blog{background:#0078D4}.t-partner{background:#008272}.t-gh{background:#24292F}
.date{font-size:.78rem;color:var(--muted);font-weight:600}
.card h3{margin:0 0 8px;font-size:1.04rem;line-height:1.35}
.card p{margin:0 0 14px;font-size:.9rem;color:#414855;flex:1}
.card-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;border-top:1px solid var(--border);padding-top:10px}
.src{font-size:.74rem;color:var(--muted);font-weight:600}.card-foot a{font-size:.8rem;font-weight:600;white-space:nowrap}
footer{background:linear-gradient(135deg,var(--azure-deep),var(--azure-dark));color:#eaf3ff;margin-top:44px;padding:44px 28px 30px}
.foot-wrap{max-width:1120px;margin:0 auto}.foot-arrow{height:30px;width:auto;margin-bottom:18px}
footer h2{color:#fff;margin:0 0 6px;font-size:1.4rem}footer .fsub{margin:0 0 24px;color:#bcd7f2;max-width:640px}
.contacts{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;max-width:1040px}
.contact{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.16);border-radius:12px;padding:18px 20px}
.contact .role{font-size:.76rem;text-transform:uppercase;letter-spacing:.04em;color:#8fc0ee;font-weight:700;margin-bottom:4px}
.contact .name{font-size:1.12rem;font-weight:700;color:#fff;margin-bottom:8px}
.contact a{color:#7fc4ff;font-weight:600;word-break:break-all}.contact .mail-row{display:flex;align-items:center;gap:8px;font-size:.92rem}
.foot-note{max-width:1120px;margin:30px auto 0;border-top:1px solid rgba(255,255,255,.14);padding-top:16px;font-size:.78rem;color:#9db8d6;line-height:1.5}
@media (max-width:520px){.hero h1{font-size:1.6rem}.topbar{padding:10px 16px}main{padding:10px 16px 30px}}
@media (prefers-color-scheme: dark){:root{--bg:#0f151d;--surface:#18202b;--ink:#eaf0f7;--muted:#9fb0c4;--border:#26303d;--shadow:0 2px 12px rgba(0,0,0,.4)}.topbar{background:#131a23}.card p{color:#c4d0de}}
</style>
</head>
<body>
<div class="topbar">
  <img class="arrow" src="data:image/png;base64,__ARROW_BLACK__" alt="Arrow">
  <div class="brand-right"><span class="brand-tag">Azure News Hub</span><span class="divider"></span>__MS_LOGO__</div>
</div>
<header class="hero">
  <h1>Microsoft Azure — News Ufficiali</h1>
  <p class="sub">Aggiornamenti, novità e annunci ufficiali della piattaforma Microsoft Azure. Curato dal team Cloud di Arrow ECS.</p>
  <div class="updated">Aggiornato al __UPDATED__</div>
  <div class="sources"><span>Microsoft Azure Blog</span><span>Azure Updates</span><span>Microsoft Learn</span><span>GitHub · Azure</span></div>
</header>
<section class="ritiri">
  <div class="ritiri-box">
    <h2>⚠️ Ritiri Azure — da tenere d'occhio</h2>
    <p class="lead">Macchine virtuali e servizi che Microsoft dismette: pianifica la migrazione prima delle date indicate. Fonti ufficiali: Microsoft Learn e Azure Updates.</p>
    <div class="ritiri-grid">
__RITIRI__
    </div>
  </div>
</section>
<div class="filterbar">
  <span class="flabel">Filtra per categoria:</span>
  <button type="button" class="chip active" data-filter="all">Tutte</button>
  <button type="button" class="chip" data-filter="ga"><span class="cdot" style="background:#107C10"></span>General Availability</button>
  <button type="button" class="chip" data-filter="preview"><span class="cdot" style="background:#8661C5"></span>Preview</button>
  <button type="button" class="chip" data-filter="ritiro"><span class="cdot" style="background:#D83B01"></span>Ritiro</button>
  <button type="button" class="chip" data-filter="blog"><span class="cdot" style="background:#0078D4"></span>Azure Blog</button>
  <button type="button" class="chip" data-filter="partner"><span class="cdot" style="background:#008272"></span>Partner</button>
  <button type="button" class="chip" data-filter="github"><span class="cdot" style="background:#24292F"></span>GitHub</button>
</div>
<main>
  <section class="section"><h2><span class="bar"></span>In evidenza — Azure Blog</h2><p class="lead">Annunci e approfondimenti dal blog ufficiale Microsoft Azure.</p><div class="grid">
__BLOG__
  </div></section>
  <section class="section"><h2><span class="bar"></span>Azure Updates</h2><p class="lead">Novità di servizio dal feed ufficiale Azure Updates — GA, Preview e ritiri.</p><div class="grid">
__UPDATES__
  </div></section>
  <section class="section"><h2><span class="bar"></span>Per i partner</h2><p class="lead">Aggiornamenti dal Microsoft Partner Center rilevanti per l'ecosistema Cloud di Arrow.</p><div class="grid">
__PARTNER__
  </div></section>
  <section class="section"><h2><span class="bar"></span>GitHub — Open source ufficiale Azure</h2><p class="lead">Repository e progetti open source mantenuti dall'organizzazione ufficiale Azure su GitHub.</p><div class="grid">
__GITHUB__
  </div></section>
</main>
<footer>
  <div class="foot-wrap">
    <img class="foot-arrow" src="data:image/png;base64,__ARROW_WHITE__" alt="Arrow">
    <h2>Hai bisogno di supporto? Contattaci</h2>
    <p class="fsub">Il team Cloud di Arrow ECS è a disposizione per approfondimenti su Microsoft Azure, progetti CSP e percorsi di adozione cloud.</p>
    <div class="contacts">
      <div class="contact"><div class="role">Microsoft Business Developer</div><div class="name">Marco Di Siero</div><div class="mail-row">✉ <a href="mailto:Marco.DiSiero@arrow.com">Marco.DiSiero@arrow.com</a></div></div>
      <div class="contact"><div class="role">Brand Manager Azure</div><div class="name">Giuseppe Cirillo</div><div class="mail-row">✉ <a href="mailto:Giuseppe.Cirillo@arrow.com">Giuseppe.Cirillo@arrow.com</a></div></div>
      <div class="contact"><div class="role">Technical Sales Engineer</div><div class="name">Gianluca Arria</div><div class="mail-row">✉ <a href="mailto:Gianluca.Arria@arrow.com">Gianluca.Arria@arrow.com</a></div></div>
    </div>
  </div>
  <div class="foot-note">Le notizie provengono da fonti ufficiali Microsoft (Azure Blog, Azure Updates, Microsoft Learn) e da GitHub (organizzazione Azure). Pagina aggiornata automaticamente al __UPDATED__. Arrow e il logo Arrow sono marchi registrati di Arrow Electronics, Inc. Microsoft, Azure e il logo Microsoft sono marchi del gruppo Microsoft.</div>
</footer>
<script>
(function(){
  var chips=document.querySelectorAll('.chip'),cards=document.querySelectorAll('.card'),sections=document.querySelectorAll('.section');
  function apply(f){
    cards.forEach(function(c){c.classList.toggle('hidden',!(f==='all'||c.getAttribute('data-cat')===f));});
    sections.forEach(function(s){s.classList.toggle('hidden',s.querySelectorAll('.card:not(.hidden)').length===0);});
  }
  chips.forEach(function(ch){ch.addEventListener('click',function(){chips.forEach(function(x){x.classList.remove('active');});ch.classList.add('active');apply(ch.getAttribute('data-filter'));});});
})();
</script>
</body>
</html>'''

out = (HTML
    .replace("__ARROW_BLACK__", arrow_black)
    .replace("__ARROW_WHITE__", arrow_white)
    .replace("__MS_LOGO__", MS_LOGO)
    .replace("__UPDATED__", UPDATED)
    .replace("__RITIRI__", render_highlight(ritiri))
    .replace("__BLOG__", render_cards(blog))
    .replace("__UPDATES__", render_cards(updates_grid))
    .replace("__PARTNER__", render_cards(partner))
    .replace("__GITHUB__", render_cards(github)))

with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as f:
    f.write(out)
print("index.html generato -", UPDATED, "-", len(out), "byte")
