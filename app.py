#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Music Sync — app local (navegador) para:
  1) Organizar mp3s da PASTA INICIAL por GÊNERO do Beatport -> PASTA FINAL/<genero>/
     (com opção de COPIAR ou MOVER)
  2) Sincronizar a PASTA FINAL com uma playlist do Spotify ("Download Sync")
Rodar:  python app.py   (abre http://127.0.0.1:8765)
Opcional: pip install --user mutagen   (melhora leitura/escrita de tags)
"""
import os, re, json, time, base64, threading, webbrowser, subprocess, sys, shutil, hashlib, collections
import urllib.parse, urllib.request, urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler, HTTPServer

HERE        = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, "config.json")
TOKEN_CACHE = os.path.join(HERE, ".spotify_token.json")
MATCH_CACHE = os.path.join(HERE, ".spotify_match_cache.json")
BP_CACHE    = os.path.join(HERE, ".beatport_cache.json")
PLAYLIST_SNAP = os.path.join(HERE, "playlist_snapshot.json")
APP_PORT    = 8765
REDIRECT_URI= "http://127.0.0.1:8888/callback"
SCOPES      = "playlist-modify-private playlist-modify-public playlist-read-private user-read-email"
UA          = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}

try:
    from mutagen.easyid3 import EasyID3
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3NoHeaderError
    HAVE_MUTAGEN = True
except Exception:
    HAVE_MUTAGEN = False

STATE = {"running": False, "logs": []}
LOCK = threading.Lock()
def log(msg):
    with LOCK: STATE["logs"].append(msg)
    print(msg)
def load_json(p, d):
    try: return json.load(open(p, encoding="utf-8"))
    except Exception: return d
def save_json(p, o):
    json.dump(o, open(p,"w",encoding="utf-8"), ensure_ascii=False, indent=2)

DEFAULTS = {"client_id":"","client_secret":"","source_dir":"","final_dir":"",
            "playlist_name":"Download Sync","op_mode":"move","dedupe_apply":False,"sync_limit":"0"}
def get_config():
    c = load_json(CONFIG_FILE, {})
    for k,v in DEFAULTS.items(): c.setdefault(k,v)
    return c

def sanitize(name):
    for k,v in {'"':"'", ':':'-','/':'-','\\':'-','|':'-','?':'','*':'','<':'(','>':')'}.items():
        name = name.replace(k,v)
    return re.sub(r"\s+"," ",name).strip().rstrip(".")
def genre_to_folder(g):
    return sanitize(g.replace(" / "," - ").replace("/"," - "))

def read_meta(path):
    base = os.path.splitext(os.path.basename(path))[0]
    artist = title = ""
    if HAVE_MUTAGEN:
        try:
            t = EasyID3(path)
            artist = (t.get("artist") or [""])[0]; title = (t.get("title") or [""])[0]
        except Exception: pass
    if not artist or not title:
        if " - " in base:
            a,b = base.split(" - ",1); artist = artist or a.strip(); title = title or b.strip()
        else: title = title or base
    return artist.strip(), title.strip()

def write_genre_tag(path, genre):
    if not HAVE_MUTAGEN or not genre: return
    try:
        try: t = EasyID3(path)
        except ID3NoHeaderError:
            m = MP3(path); m.add_tags(); m.save(); t = EasyID3(path)
        t["genre"] = genre; t.save()
    except Exception: pass

# ---------- Beatport (best-effort) ----------
def http_get(url, timeout=20):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read().decode("utf-8","ignore")
def beatport_track_url(artist, title):
    q = f"{artist} {title} beatport".strip()
    try: page = http_get("https://html.duckduckgo.com/html/?q="+urllib.parse.quote(q))
    except Exception as e: log(f"   (busca falhou: {e})"); return None
    page = urllib.parse.unquote(page)
    m = re.findall(r"https://www\.beatport\.com/track/[a-zA-Z0-9\-]+/\d+", page)
    return m[0] if m else None
def beatport_genre_from_page(url):
    try: page = http_get(url)
    except Exception: return None
    for p in (r'"genre"\s*:\s*\{\s*"id"\s*:\s*\d+\s*,\s*"name"\s*:\s*"([^"]+)"',
              r'"genre"\s*:\s*\[\s*\{\s*"id"\s*:\s*\d+\s*,\s*"name"\s*:\s*"([^"]+)"',
              r'/genre/[a-z0-9\-]+/\d+"[^>]*>\s*([A-Za-z0-9 /&\-\(\)]+?)\s*<'):
        m = re.search(p, page)
        if m and m.group(1).strip().lower()!="genre": return m.group(1).strip()
    return None
def beatport_lookup(artist, title, cache):
    key = f"{artist}|{title}".lower()
    if key in cache: return cache[key]
    url = beatport_track_url(artist, title)
    genre = beatport_genre_from_page(url) if url else None
    cache[key] = genre; save_json(BP_CACHE, cache); time.sleep(1.0)
    return genre

def organize(source, final, mode):
    if not os.path.isdir(source): log(f"Pasta inicial inválida: {source}"); return
    if not final: log("Defina a pasta final."); return
    os.makedirs(final, exist_ok=True)
    verb = "Copiando" if mode=="copy" else "Movendo"
    loose = [f for f in os.listdir(source) if f.lower().endswith(".mp3") and os.path.isfile(os.path.join(source,f))]
    if not loose: log(f"Nenhum mp3 na pasta inicial: {source}"); return
    cache = load_json(BP_CACHE, {})
    log(f"{verb} {len(loose)} arquivo(s) da pasta inicial -> pasta final, por gênero do Beatport...\n")
    done=0
    for i,f in enumerate(sorted(loose),1):
        src = os.path.join(source,f)
        artist,title = read_meta(src)
        genre = beatport_lookup(artist, title, cache) or "Unknown"
        folder = genre_to_folder(genre) if genre!="Unknown" else "Unknown"
        dest_dir = os.path.join(final, folder); os.makedirs(dest_dir, exist_ok=True)
        newbase = sanitize(f"{artist} - {title}")+".mp3" if artist and title else f
        dest = os.path.join(dest_dir, newbase); st,ext = os.path.splitext(newbase); n=1
        while os.path.exists(dest):
            n+=1; dest = os.path.join(dest_dir, f"{st} ({n}){ext}")
        try:
            if mode=="copy":
                shutil.copy2(src, dest)
                if genre!="Unknown": write_genre_tag(dest, genre)
            else:
                shutil.move(src, dest)
                if genre!="Unknown": write_genre_tag(dest, genre)
            done+=1
            log(f"[{i}/{len(loose)}] {f}  ->  {folder}/  ({genre})")
        except Exception as e:
            log(f"[{i}/{len(loose)}] ERRO em {f}: {e}")
    log(f"\nConcluído. {('Copiados' if mode=='copy' else 'Movidos')}: {done}.")

# ---------- Spotify ----------
API="https://api.spotify.com/v1"; AUTH="https://accounts.spotify.com"
def sp_req(url, token=None, method="GET", data=None, basic=None):
    headers={}
    if token: headers["Authorization"]=f"Bearer {token}"
    if basic: headers["Authorization"]=basic
    if isinstance(data,dict) and not basic:
        data=json.dumps(data).encode(); headers["Content-Type"]="application/json"
    req=urllib.request.Request(url,data=data,method=method,headers=headers)
    while True:
        try:
            with urllib.request.urlopen(req) as r:
                b=r.read().decode(); return r.status,(json.loads(b) if b else {})
        except urllib.error.HTTPError as e:
            if e.code==429:
                wait=int(e.headers.get("Retry-After","2"))+1
                if wait>120: log(f"*** Limite temporário do Spotify (~{round(wait/3600,1)}h). Rode mais tarde. ***"); raise SystemExit
                log(f"   (rate limit, {wait}s)"); time.sleep(wait); continue
            b=e.read().decode()
            try: b=json.loads(b)
            except: pass
            return e.code,b
_auth_code={}
class CB(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_GET(self):
        _auth_code["code"]=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("code",[None])[0]
        self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.end_headers()
        self.wfile.write("<h2>Autorizado! Pode fechar esta aba.</h2>".encode())
def sp_token(cid, secret):
    basic="Basic "+base64.b64encode(f"{cid}:{secret}".encode()).decode()
    cache=load_json(TOKEN_CACHE,{})
    if cache.get("refresh_token") and cache.get("scopes")==SCOPES:
        data=urllib.parse.urlencode({"grant_type":"refresh_token","refresh_token":cache["refresh_token"]}).encode()
        st,js=sp_req(f"{AUTH}/api/token",method="POST",data=data,basic=basic)
        if st==200 and js.get("access_token"): return js["access_token"]
    url=f"{AUTH}/authorize?"+urllib.parse.urlencode({"client_id":cid,"response_type":"code","redirect_uri":REDIRECT_URI,"scope":SCOPES})
    srv=HTTPServer(("127.0.0.1",8888),CB); t=threading.Thread(target=srv.handle_request); t.start()
    log("Abra o navegador para autorizar (deve abrir sozinho)."); webbrowser.open(url)
    t.join(timeout=300); srv.server_close()
    code=_auth_code.get("code")
    if not code: log("Autorização não recebida."); return None
    data=urllib.parse.urlencode({"grant_type":"authorization_code","code":code,"redirect_uri":REDIRECT_URI}).encode()
    st,js=sp_req(f"{AUTH}/api/token",method="POST",data=data,basic=basic)
    if st!=200: log(f"Falha no token: {js}"); return None
    save_json(TOKEN_CACHE,{"refresh_token":js.get("refresh_token"),"scopes":SCOPES}); return js["access_token"]
def norm(s):
    s=re.sub(r"\(.*?\)|\[.*?\]"," ",s.lower())
    return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9 ]"," ",s)).strip()
def list_all_tracks(root):
    out=[]
    for r,_,fs in os.walk(root):
        for f in fs:
            if f.lower().endswith(".mp3"):
                a,t=read_meta(os.path.join(r,f)); out.append((a,t,os.path.splitext(f)[0]))
    out.sort(key=lambda x:x[2].lower()); return out
def sync(cid, secret, final, playlist_name, limit):
    if not os.path.isdir(final): log(f"Pasta final inválida: {final}"); return
    if not cid or not secret: log("Preencha Client ID e Client Secret."); return
    try: limit=int(str(limit).strip() or "0")
    except Exception: limit=0
    token=sp_token(cid,secret)
    if not token: return
    st,me=sp_req(f"{API}/me",token=token)
    if st!=200: log(f"Erro /me: {me}"); return
    uid=me["id"]; log(f"Conta: {me.get('display_name',uid)}")
    # achar playlist
    pid=None; url=f"{API}/me/playlists?limit=50"
    while url:
        st,js=sp_req(url,token=token)
        if st!=200: log(f"Erro playlists: {js}"); return
        for pl in js.get("items",[]):
            if pl and pl.get("name")==playlist_name and pl.get("owner",{}).get("id")==uid: pid=pl["id"]; break
        if pid: break
        url=js.get("next")
    if not pid:
        st,js=sp_req(f"{API}/users/{uid}/playlists",method="POST",token=token,data={"name":playlist_name,"public":False,"description":"Musicas baixadas (sync)"})
        if st in (200,201) and "id" in js: pid=js["id"]; log(f"Playlist '{playlist_name}' criada.")
        else: log(f"Nao consegui criar a playlist (HTTP {st}). Crie uma playlist chamada '{playlist_name}' no app do Spotify e tente de novo."); return
    else: log(f"Playlist '{playlist_name}' encontrada.")
    # 1) ler a playlist atual e salvar snapshot local (parser robusto p/ a API nova)
    have=set(); snap=[]; api_total=None; raw_items=0; first_raw=None
    url=f"{API}/playlists/{pid}/items?limit=100&additional_types=track"
    while url:
        st,js=sp_req(url,token=token)
        if st!=200: log(f"   (erro lendo playlist HTTP {st}: {js})"); break
        if api_total is None: api_total=js.get("total")
        page=js.get("items") or (js.get("tracks",{}) or {}).get("items") or []
        raw_items+=len(page)
        for it in page:
            if first_raw is None: first_raw=it
            tr=None
            if isinstance(it,dict):
                for key in ("track","item","episode"):
                    v=it.get(key)
                    if isinstance(v,dict): tr=v; break
                if tr is None and it.get("uri"): tr=it
            if not isinstance(tr,dict): continue
            u=tr.get("uri")
            if u and "track" in u:
                have.add(u)
                snap.append({"uri":u,"name":tr.get("name",""),"artists":", ".join(a.get("name","") for a in tr.get("artists",[]))})
        url=js.get("next")
    save_json(PLAYLIST_SNAP, {"playlist":playlist_name,"id":pid,"count":len(have),"tracks":snap})
    log(f"Playlist '{playlist_name}': {len(have)} faixa(s) lidas (itens brutos: {raw_items}, total API: {api_total}).")
    if len(have)==0 and raw_items>0 and first_raw is not None:
        save_json(os.path.join(HERE,"_debug_item.json"), first_raw)
        log("AVISO: a playlist tem itens mas não consegui ler as URIs. Salvei _debug_item.json — me envie esse arquivo.")
    # 2) comparar com a pasta final; candidatos = faixas que ainda NÃO estão na playlist
    tracks=list_all_tracks(final); match=load_json(MATCH_CACHE,{})
    already=0; cached_nf=0; candidates=[]   # cada candidato: (artist,title,base,uri_ou_None)
    for (a,t,base) in tracks:
        if base in match:
            uri=match[base]
            if uri is None: cached_nf+=1            # já sabido que não existe no Spotify -> ignora
            elif uri in have: already+=1            # já está na playlist -> ignora
            else: candidates.append((a,t,base,uri)) # tem URI no cache, falta adicionar
        else:
            candidates.append((a,t,base,None))      # desconhecida -> precisa buscar
    log(f"Local: {len(tracks)} | já na playlist: {already} | faltando: {len(candidates)} | não encontradas (cache): {cached_nf}")
    if limit>0 and len(candidates)>limit:
        log(f"** LIMITE ativo: processando só {limit} de {len(candidates)} faixas faltantes nesta execução **")
        candidates=candidates[:limit]
    # 3) resolver candidatos (busca só quem não tem URI no cache = 1 chamada cada)
    seen=set(); to_add=[]; nf=0
    for i2,(a,t,base,uri) in enumerate(candidates,1):
        if uri is None:
            q=norm(f"{a} {t}") or norm(base)
            st,js=sp_req(f"{API}/search?"+urllib.parse.urlencode({"q":q,"type":"track","limit":5}),token=token)
            items=(js.get("tracks") or {}).get("items",[]) if st==200 else []
            uri=items[0]["uri"] if items else None
            match[base]=uri; save_json(MATCH_CACHE,match); time.sleep(0.3)
        if not uri: nf+=1; log(f"[{i2}/{len(candidates)}] x {base}"); continue
        if uri in have or uri in seen: log(f"[{i2}/{len(candidates)}] = {base} (já estava)"); continue
        seen.add(uri); to_add.append(uri); log(f"[{i2}/{len(candidates)}] + {base}")
    # 4) adicionar (em lotes de 100)
    for k in range(0,len(to_add),100):
        st,js=sp_req(f"{API}/playlists/{pid}/items",method="POST",token=token,data={"uris":to_add[k:k+100]})
        if st not in (200,201): log(f"Erro ao adicionar lote (HTTP {st}): {js}")
    log(f"\nConcluído. Adicionadas agora: {len(to_add)}. Não encontradas nesta execução: {nf}.")

def dedupe(final, apply):
    if not os.path.isdir(final): log(f"Pasta final inválida: {final}"); return
    files=[os.path.join(r,f) for r,_,fs in os.walk(final) for f in fs if f.lower().endswith(".mp3")]
    if not files: log("Nenhum mp3 na pasta final."); return
    log(f"Analisando {len(files)} arquivo(s)...  (modo: {'REMOVER de fato' if apply else 'apenas prévia'})\n")
    STOP={"the","a","an","feat","ft","and","de","do","da"}
    def toks(p):
        sn=re.sub(r"[^a-z0-9 ]"," ",os.path.splitext(os.path.basename(p))[0].lower())
        return frozenset(w for w in sn.split() if w not in STOP and len(w)>1)
    def dur(p):
        if HAVE_MUTAGEN:
            try: return round(MP3(p).info.length)
            except Exception: return None
        return None
    def md5(p):
        h=hashlib.md5()
        with open(p,"rb") as fh:
            for c in iter(lambda: fh.read(1<<20), b""): h.update(c)
        return h.hexdigest()
    size={p:os.path.getsize(p) for p in files}
    tok={p:toks(p) for p in files}
    durc={p:dur(p) for p in files}
    def keep_of(grp):
        def sc(p):
            unk=0 if os.path.basename(os.path.dirname(p)).lower()=="unknown" else 1
            return (unk,size[p],len(os.path.basename(p)))
        return max(grp,key=sc)
    groups=[]
    bysize=collections.defaultdict(list)
    for p in files: bysize[size[p]].append(p)
    md5map=collections.defaultdict(list)
    for sz,grp in bysize.items():
        if len(grp)>1:
            for p in grp: md5map[md5(p)].append(p)
    for h,grp in md5map.items():
        if len(grp)>1: groups.append(("idênticos (mesmo áudio)",grp))
    bytok=collections.defaultdict(list)
    for p in files: bytok[tok[p]].append(p)
    for t,grp in bytok.items():
        if len(grp)<2: continue
        clusters=[]
        for p in sorted(grp,key=lambda x:(durc[x] is None, durc[x] or 0)):
            placed=False
            for cl in clusters:
                d0=durc[cl[0]]; d=durc[p]
                if (d0 is None or d is None) or abs((d0 or 0)-(d or 0))<=2:
                    cl.append(p); placed=True; break
            if not placed: clusters.append([p])
        for cl in clusters:
            if len(cl)>1: groups.append(("mesmo nome + duração",cl))
    handled=set(); removed=0; seen=set()
    for label,grp in groups:
        grp=[x for x in grp if x not in seen]
        if len(grp)<2: continue
        keep=keep_of(grp); seen.update(grp); handled.update(grp)
        log(f"[{label}] manter: {os.path.relpath(keep,final)}")
        for p in grp:
            if p==keep: continue
            log(f"    remover: {os.path.relpath(p,final)}")
            if apply:
                try: os.remove(p); removed+=1
                except Exception as e: log(f"      (falha: {e})")
        log("")
    rest=[p for p in files if p not in handled]
    review=[]
    for i in range(len(rest)):
        for j in range(i+1,len(rest)):
            a,b=rest[i],rest[j]; ta,tb=tok[a],tok[b]
            if not ta or not tb: continue
            inter=ta&tb; jac=len(inter)/len(ta|tb)
            if ((ta<=tb or tb<=ta) and min(len(ta),len(tb))>=2) or jac>=0.6:
                review.append((a,b,round(jac,2)))
    if review:
        log("Possíveis duplicatas para revisar à mão (NÃO removidas — podem ser versões diferentes):")
        for a,b,jac in review:
            log(f"  ~{jac}  {os.path.relpath(a,final)}  [{durc[a]}s]")
            log(f"          {os.path.relpath(b,final)}  [{durc[b]}s]")
        log("")
    log(f"Concluído. {('Removidos: '+str(removed)) if apply else 'Prévia (nada foi removido).'}  Para revisar à mão: {len(review)} par(es).")

def run_job(fn,*a):
    def wrap():
        with LOCK: STATE["running"]=True
        try: fn(*a)
        except SystemExit: pass
        except Exception as e: log(f"ERRO: {e}")
        finally:
            with LOCK: STATE["running"]=False
            log("__DONE__")
    threading.Thread(target=wrap,daemon=True).start()
def pick_folder():
    code=('import tkinter as tk;from tkinter import filedialog;'
          'r=tk.Tk();r.withdraw();r.attributes("-topmost",True);print(filedialog.askdirectory() or "")')
    try: return subprocess.run([sys.executable,"-c",code],capture_output=True,text=True,timeout=120).stdout.strip()
    except Exception: return ""

PAGE = open(os.path.join(HERE,"index.html"),encoding="utf-8").read() if os.path.exists(os.path.join(HERE,"index.html")) else "<h1>index.html ausente</h1>"
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _send(self,code,ctype,body):
        self.send_response(code); self.send_header("Content-Type",ctype); self.end_headers()
        self.wfile.write(body if isinstance(body,bytes) else body.encode())
    def do_GET(self):
        u=urllib.parse.urlparse(self.path)
        if u.path=="/": return self._send(200,"text/html; charset=utf-8",PAGE)
        if u.path=="/api/config": return self._send(200,"application/json",json.dumps(get_config()))
        if u.path=="/api/logs":
            since=int(urllib.parse.parse_qs(u.query).get("since",["0"])[0])
            with LOCK: lines=STATE["logs"][since:]; running=STATE["running"]
            return self._send(200,"application/json",json.dumps({"lines":lines,"running":running,"total":since+len(lines)}))
        return self._send(404,"text/plain","not found")
    def do_POST(self):
        u=urllib.parse.urlparse(self.path)
        ln=int(self.headers.get("Content-Length","0") or 0)
        body=json.loads(self.rfile.read(ln) or "{}") if ln else {}
        if u.path=="/api/config":
            cfg=get_config(); cfg.update({k:body.get(k,cfg[k]) for k in DEFAULTS})
            save_json(CONFIG_FILE,cfg); return self._send(200,"application/json",json.dumps({"ok":True}))
        if u.path=="/api/pick-folder":
            return self._send(200,"application/json",json.dumps({"path":pick_folder()}))
        if u.path in ("/api/organize","/api/sync","/api/dedupe"):
            with LOCK:
                if STATE["running"]: return self._send(200,"application/json",json.dumps({"ok":False,"msg":"já rodando"}))
                STATE["logs"]=[]
            c=get_config()
            if u.path=="/api/organize": run_job(organize,c["source_dir"],c["final_dir"],c["op_mode"])
            elif u.path=="/api/dedupe": run_job(dedupe,c["final_dir"],bool(c["dedupe_apply"]))
            else: run_job(sync,c["client_id"],c["client_secret"],c["final_dir"],c["playlist_name"],c["sync_limit"])
            return self._send(200,"application/json",json.dumps({"ok":True}))
        return self._send(404,"text/plain","not found")
def main():
    srv=ThreadingHTTPServer(("127.0.0.1",APP_PORT),Handler); url=f"http://127.0.0.1:{APP_PORT}"
    print(f"Music Sync rodando em {url}  (Ctrl+C para sair)")
    print("mutagen:", "OK" if HAVE_MUTAGEN else "ausente (rode: pip install --user mutagen)")
    try: webbrowser.open(url)
    except Exception: pass
    try: srv.serve_forever()
    except KeyboardInterrupt: print("\nencerrado.")
if __name__=="__main__": main()
