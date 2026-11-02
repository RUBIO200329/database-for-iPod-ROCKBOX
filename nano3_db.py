#!/usr/bin/env python3
"""nano3_db.py — Genera la base de datos REAL de Rockbox (tagcache) para un iPod nano 3G (FAT32).

Compila la herramienta oficial de base de datos del repo giek2000/Nano3Rockbox
(tools/database, `configure --type=d`) y la ejecuta en la raíz del iPod, que es
como Rockbox espera que se genere: escribe /.rockbox/database_idx.tcd y
/.rockbox/database_0..N.tcd con el formato exacto que lee el firmware
(magic 0x54434810, enteros de 32 bits little-endian).

Uso:
  ./nano3_db.py                       # autodetecta el iPod montado
  ./nano3_db.py /run/media/$USER/IPOD
  ./nano3_db.py --copy-music ~/MusicaiPhone4S    # copia primero la música a /Music
  ./nano3_db.py --dry-run | --rebuild | --eject | --dbtool RUTA

Requisitos (Ubuntu): sudo apt install git build-essential perl libsdl2-dev rsync
                     (Arch/CachyOS: sudo pacman -S git base-devel perl sdl2 rsync)
Las rutas de la base se guardan relativas a la raíz del iPod, así que la música
tiene que estar ya en el iPod cuando se genera (por eso --copy-music).
"""
import argparse, glob, json, os, shutil, struct, subprocess, sys, time
from pathlib import Path

REPO = "https://github.com/giek2000/Nano3Rockbox.git"
CACHE = Path.home() / ".cache" / "nano3-dbtool"
TAGCACHE_MAGIC = 0x54434810
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav", ".wv", ".ape", ".mpc"}


def die(msg):
    sys.exit(f"ERROR: {msg}")


def run(cmd, dry=False, **kw):
    print("$", " ".join(str(c) for c in cmd))
    if dry:
        return None
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


# ---------------------------------------------------------------- iPod -----
def mounts():
    out = subprocess.run(["findmnt", "-lJ", "-o", "TARGET,FSTYPE,SOURCE"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)["filesystems"]


def find_ipod():
    for m in mounts():
        if m["fstype"] == "vfat" and (Path(m["target"]) / ".rockbox").is_dir():
            return Path(m["target"])
    return None


def mount_info(path):
    best = None
    for m in mounts():
        t = m["target"]
        if str(path) == t or str(path).startswith(t.rstrip("/") + "/"):
            if best is None or len(t) > len(best["target"]):
                best = m
    return best


# ------------------------------------------------------------- dbtool ------
def build_dbtool(rebuild):
    src, build = CACHE / "repo", CACHE / "build"
    existing = sorted(glob.glob(str(build / "database*")))
    existing = [p for p in existing if os.access(p, os.X_OK) and os.path.isfile(p)]
    if existing and not rebuild:
        return Path(existing[0])

    missing = [t for t in ("git", "make", "gcc", "perl", "sdl2-config") if not shutil.which(t)]
    if missing:
        die("faltan herramientas: " + ", ".join(missing) +
            "\n  Ubuntu: sudo apt install git build-essential perl libsdl2-dev")

    CACHE.mkdir(parents=True, exist_ok=True)
    if (src / ".git").is_dir():
        subprocess.run(["git", "-C", str(src), "pull", "--ff-only"], check=False)
    else:
        run(["git", "clone", "--depth", "1", REPO, src])

    if build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True)
    run([src / "tools" / "configure", "--target=ipodnano3g", "--type=d"],
        cwd=build, stdin=subprocess.DEVNULL)
    run(["make", f"-j{os.cpu_count() or 2}"], cwd=build)

    bins = [p for p in glob.glob(str(build / "database*"))
            if os.access(p, os.X_OK) and os.path.isfile(p)]
    if not bins:
        die("la compilación terminó pero no encuentro el binario 'database.*'")
    return Path(bins[0])


# ------------------------------------------------------------- database ----
def count_audio(root):
    n = 0
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d != ".rockbox" and not d.startswith(".")]
        n += sum(1 for f in fn if Path(f).suffix.lower() in AUDIO_EXT)
    return n


def verify(rb, expected):
    idx = rb / "database_idx.tcd"
    if not idx.is_file():
        die("la herramienta no generó database_idx.tcd")
    hdr = idx.read_bytes()[:24]
    if len(hdr) < 24:
        die("database_idx.tcd está truncado")
    magic, datasize, entries, serial, commitid, dirty = struct.unpack("<6i", hdr)
    if magic != TAGCACHE_MAGIC:
        die(f"database_idx.tcd con magic inválido (0x{magic & 0xffffffff:08x})")
    parts = sorted(rb.glob("database_[0-9]*.tcd"))
    if not parts:
        die("no hay ficheros database_N.tcd")
    for p in parts:
        m = struct.unpack("<i", p.read_bytes()[:4].ljust(4, b"\0"))[0]
        if m != TAGCACHE_MAGIC:
            die(f"{p.name} tiene un header inválido")
    print(f"OK: {entries} pistas indexadas, {len(parts)} ficheros de etiquetas.")
    if entries == 0:
        die("la base de datos quedó vacía (¿hay música con etiquetas en el iPod?)")
    if entries < expected:
        print(f"AVISO: {expected} archivos de audio en el iPod pero {entries} en la base "
              "(los que no tienen formato/etiquetas legibles se omiten).")


def main():
    ap = argparse.ArgumentParser(description="Genera la database de Rockbox para iPod nano 3G")
    ap.add_argument("mount", nargs="?", help="punto de montaje del iPod")
    ap.add_argument("--copy-music", metavar="DIR", help="copia DIR a <iPod>/Music antes de indexar")
    ap.add_argument("--dbtool", help="usar este binario en vez de compilar el del repo")
    ap.add_argument("--rebuild", action="store_true", help="recompilar la herramienta")
    ap.add_argument("--eject", action="store_true", help="desmontar y apagar el iPod al terminar")
    ap.add_argument("-n", "--dry-run", action="store_true", help="no escribe nada en el iPod")
    ap.add_argument("--allow-non-fat", action="store_true", help="(solo pruebas) no exigir vfat")
    a = ap.parse_args()

    ipod = Path(a.mount) if a.mount else find_ipod()
    if not ipod or not ipod.is_dir():
        die("no encuentro el iPod; pasa el punto de montaje (debe contener /.rockbox)")
    rb = ipod / ".rockbox"
    if not rb.is_dir():
        die(f"{ipod} no tiene /.rockbox (¿Rockbox instalado en este volumen?)")
    info = mount_info(ipod)
    if info and info["fstype"] != "vfat" and not a.allow_non_fat:
        die(f"{ipod} es {info['fstype']}, no FAT32/vfat")
    if not a.dry_run and not os.access(ipod, os.W_OK):
        die(f"{ipod} no es escribible (¿solo lectura?)")
    print(f"iPod: {ipod} ({info['fstype'] if info else '?'})")

    tool = Path(a.dbtool) if a.dbtool else build_dbtool(a.rebuild)
    if not tool.is_file() or not os.access(tool, os.X_OK):
        die(f"{tool} no es ejecutable")
    tool = tool.resolve()
    print(f"Herramienta: {tool}")

    if a.copy_music:
        src = Path(a.copy_music).expanduser()
        if not src.is_dir():
            die(f"{src} no es un directorio")
        if not shutil.which("rsync"):
            die("falta rsync (sudo apt install rsync)")
        run(["rsync", "-rt", "--modify-window=2", "--no-perms", "--no-owner", "--no-group",
             "--info=progress2", f"{src}/", ipod / "Music/"], dry=a.dry_run)

    expected = count_audio(ipod)
    print(f"Archivos de audio en el iPod: {expected}")
    if expected == 0:
        die("no hay música en el iPod; usa --copy-music o cópiala antes de indexar")

    # Respaldo y limpieza de la base anterior (equivale a 'Initialise Now':
    # se pierden playcounts/valoraciones guardados en la base).
    old = [p for pat in ("database_*.tcd", "tagcache_*.tcd", "database_*.txt", "tagcache_*.txt")
           for p in rb.glob(pat)]
    if old:
        bk = CACHE / "backup" / time.strftime("%Y%m%d-%H%M%S")
        print(f"Respaldando {len(old)} ficheros antiguos en {bk}")
        if not a.dry_run:
            bk.mkdir(parents=True)
            for p in old:
                shutil.copy2(p, bk / p.name)
                p.unlink()

    print("Generando la base de datos (puede tardar)...")
    if a.dry_run:
        print(f"[dry] (cd {ipod} && {tool})")
        return
    subprocess.run([str(tool)], cwd=ipod, check=True)
    verify(rb, expected)

    print("Sincronizando...")
    os.sync()
    if a.eject and info:
        src_dev = info["source"]
        run(["udisksctl", "unmount", "-b", src_dev])
        parent = src_dev.rstrip("0123456789")
        subprocess.run(["udisksctl", "power-off", "-b", parent], check=False)
    print("Listo. Desconecta el iPod y en Rockbox: Database > Database Menu > "
          "'Load to RAM' (opcional). Si algo falla, 'Initialise Now' lo regenera en el propio iPod.")


if __name__ == "__main__":
    main()
