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
  ./nano3_db.py --art 128             # (opcional) reduce las carátulas incrustadas a 128 px
  ./nano3_db.py --dry-run | --rebuild | --eject | --dbtool RUTA

Sin --art no se toca ningún archivo de música. Con --art N las carátulas MP3
incrustadas que midan más de N px se reescalan a N px (el audio no se recodifica
y las que ya son pequeñas se saltan, así que se puede repetir sin problema).
OJO: un `--copy-music` posterior vuelve a copiar los originales (rsync ve que
el tamaño cambió); usa --art de nuevo después de copiar.

Requisitos (Ubuntu): sudo apt install git build-essential perl libsdl2-dev rsync
                     (Fedora:  sudo dnf install git make gcc perl SDL2-devel rsync)
                     (Arch/CachyOS: sudo pacman -S git base-devel perl sdl2 rsync)
Para --art además hace falta ffmpeg (incluye ffprobe).
Las rutas de la base se guardan relativas a la raíz del iPod, así que la música
tiene que estar ya en el iPod cuando se genera (por eso --copy-music).
"""
import argparse, glob, json, os, re, shutil, struct, subprocess, sys, tempfile, time
from pathlib import Path

REPO = "https://github.com/giek2000/Nano3Rockbox.git"
CACHE = Path.home() / ".cache" / "nano3-dbtool"
TAGCACHE_MAGIC = 0x54434810
DBTOOL_NAME = "database.ipodnano3g"   # nombre que genera tools/configure para este target
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav", ".wv", ".ape", ".mpc"}
ART_EXT = {".mp3"}                    # formatos cuyas carátulas sabe reescalar --art


def die(msg):
    sys.exit(f"ERROR: {msg}")


def run(cmd, dry=False, **kw):
    print("$", " ".join(str(c) for c in cmd))
    if dry:
        return None
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def install_hint():
    """Comando de instalación de dependencias según la distribución."""
    ids = ""
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith(("ID=", "ID_LIKE=")):
                    ids += line.split("=", 1)[1].strip().strip('"').lower() + " "
    except OSError:
        pass
    if any(d in ids for d in ("fedora", "rhel", "centos")):
        return "sudo dnf install git make gcc perl SDL2-devel rsync"
    if any(d in ids for d in ("arch", "cachyos", "manjaro")):
        return "sudo pacman -S git base-devel perl sdl2 rsync"
    return "sudo apt install git build-essential perl libsdl2-dev rsync"


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


def parent_device(dev):
    """/dev/sdb1 -> /dev/sdb ; /dev/mmcblk0p1 -> /dev/mmcblk0 ; /dev/nvme0n1p1 -> /dev/nvme0n1"""
    if re.search(r"(mmcblk|nvme|loop)\d", dev):
        return re.sub(r"p\d+$", "", dev)
    return dev.rstrip("0123456789")


# ------------------------------------------------------------- dbtool ------
def find_built_tool(build):
    exact = build / DBTOOL_NAME
    if exact.is_file() and os.access(exact, os.X_OK):
        return exact
    for p in sorted(glob.glob(str(build / "database*"))):
        if os.path.isfile(p) and os.access(p, os.X_OK) and not p.endswith((".o", ".d")):
            return Path(p)
    return None


def build_dbtool(rebuild):
    src, build = CACHE / "repo", CACHE / "build"
    existing = find_built_tool(build)
    if existing and not rebuild:
        return existing

    missing = [t for t in ("git", "make", "gcc", "perl", "sdl2-config") if not shutil.which(t)]
    if missing:
        die("faltan herramientas: " + ", ".join(missing) + f"\n  Instala con: {install_hint()}")

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

    tool = find_built_tool(build)
    if not tool:
        die(f"la compilación terminó pero no encuentro el binario '{DBTOOL_NAME}'")
    return tool


# ---------------------------------------------------------- carátulas ------
def probe_art(path):
    """(ancho, alto) de la primera imagen incrustada, o None si no tiene."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    out = r.stdout.strip().splitlines()
    if r.returncode != 0 or not out:
        return None
    try:
        w, h = out[0].split(",")[:2]
        return int(w), int(h)
    except ValueError:
        return None


def resize_art(root, size, dry=False):
    """Reescala a `size` px las carátulas MP3 incrustadas mayores que eso (sin tocar el audio)."""
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            die(f"falta {tool} (necesario para --art); instala ffmpeg "
                "(Fedora: ffmpeg-free o ffmpeg de RPM Fusion)")

    files = sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in ART_EXT
        and not any(part.startswith(".") for part in p.relative_to(root).parts))
    print(f"Carátulas: analizando {len(files)} archivos MP3 en {root} ...")

    todo, no_art, small = [], 0, 0
    for p in files:
        dims = probe_art(p)
        if dims is None:
            no_art += 1
        elif max(dims) <= size:
            small += 1
        else:
            todo.append(p)
    print(f"  {len(todo)} por reescalar a {size}px · {small} ya pequeñas · {no_art} sin carátula")
    if not todo or dry:
        if dry and todo:
            print("[dry] no se modifica ninguna carátula")
        return

    tmpdir = Path(tempfile.mkdtemp(prefix="nano3art-"))
    errors, t0 = [], time.time()
    try:
        for i, p in enumerate(todo, 1):
            tmp = tmpdir / "x.mp3"
            st = p.stat()
            r = subprocess.run(
                ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(p),
                 "-map", "0:a", "-map", "0:v:0", "-c:a", "copy", "-c:v", "mjpeg", "-q:v", "5",
                 "-vf", f"scale={size}:{size}:force_original_aspect_ratio=decrease",
                 "-disposition:v", "attached_pic", "-map_metadata", "0",
                 "-id3v2_version", "3", str(tmp)],
                capture_output=True, text=True)
            if r.returncode != 0 or not tmp.is_file():
                errors.append((p, r.stderr.strip().splitlines()[-1:] or ["?"]))
            else:
                shutil.move(str(tmp), str(p))
                os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
            eta = int((time.time() - t0) * (len(todo) - i) / i / 60)
            print(f"\r  {i}/{len(todo)} ({i * 100 // len(todo)}%)  quedan ~{eta} min   ",
                  end="", flush=True)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    print()
    os.sync()
    if errors:
        print(f"AVISO: {len(errors)} archivos no se pudieron reescalar (se dejaron intactos):")
        for p, msg in errors[:10]:
            print(f"  - {p.name}: {msg[0]}")


# ------------------------------------------------------------- database ----
def count_audio(root):
    n = 0
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d != ".rockbox" and not d.startswith(".")]
        n += sum(1 for f in fn if Path(f).suffix.lower() in AUDIO_EXT)
    return n


def read_head(path, n):
    with open(path, "rb") as f:
        return f.read(n)


def verify(rb, expected):
    idx = rb / "database_idx.tcd"
    if not idx.is_file():
        die("la herramienta no generó database_idx.tcd")
    hdr = read_head(idx, 24)
    if len(hdr) < 24:
        die("database_idx.tcd está truncado")
    magic, datasize, entries, serial, commitid, dirty = struct.unpack("<6i", hdr)
    if magic != TAGCACHE_MAGIC:
        die(f"database_idx.tcd con magic inválido (0x{magic & 0xffffffff:08x})")
    parts = sorted(rb.glob("database_[0-9]*.tcd"))
    if not parts:
        die("no hay ficheros database_N.tcd")
    for p in parts:
        m = struct.unpack("<i", read_head(p, 4).ljust(4, b"\0"))[0]
        if m != TAGCACHE_MAGIC:
            die(f"{p.name} tiene un header inválido")
    print(f"OK: {entries} pistas indexadas, {len(parts)} ficheros de etiquetas.")
    if entries == 0:
        die("la base de datos quedó vacía (¿hay música con etiquetas en el iPod?)")
    if entries < expected:
        print(f"AVISO: {expected} archivos de audio en el iPod pero {entries} en la base "
              "(los que no tienen formato/etiquetas legibles se omiten).")


def restore_backup(rb, bk):
    """Quita lo generado a medias y devuelve la base anterior."""
    for p in rb.glob("database_*.tcd"):
        p.unlink()
    if bk and bk.is_dir():
        for p in bk.iterdir():
            shutil.copy2(p, rb / p.name)
        os.sync()
        print(f"La generación falló: se restauró la base anterior desde {bk}")
    else:
        print("La generación falló y no había una base anterior que restaurar.")


def main():
    ap = argparse.ArgumentParser(description="Genera la database de Rockbox para iPod nano 3G")
    ap.add_argument("mount", nargs="?", help="punto de montaje del iPod")
    ap.add_argument("--copy-music", metavar="DIR", help="copia DIR a <iPod>/Music antes de indexar")
    ap.add_argument("--art", type=int, metavar="PX",
                    help="(opcional) reescala las carátulas MP3 incrustadas a PX píxeles; "
                         "sin esta opción no se modifica la música")
    ap.add_argument("--dbtool", help="usar este binario en vez de compilar el del repo")
    ap.add_argument("--rebuild", action="store_true", help="recompilar la herramienta")
    ap.add_argument("--eject", action="store_true", help="desmontar y apagar el iPod al terminar")
    ap.add_argument("-n", "--dry-run", action="store_true", help="no escribe nada en el iPod")
    ap.add_argument("--allow-non-fat", action="store_true", help="(solo pruebas) no exigir vfat")
    a = ap.parse_args()
    if a.art is not None and not 16 <= a.art <= 1024:
        die("--art debe estar entre 16 y 1024 píxeles (p. ej. --art 128)")

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
            die(f"falta rsync ({install_hint()})")
        run(["rsync", "-rt", "--modify-window=2", "--no-perms", "--no-owner", "--no-group",
             "--info=progress2", f"{src}/", ipod / "Music/"], dry=a.dry_run)

    if a.art is not None:
        music = ipod / "Music"
        resize_art(music if music.is_dir() else ipod, a.art, dry=a.dry_run)

    expected = count_audio(ipod)
    print(f"Archivos de audio en el iPod: {expected}")
    if expected == 0:
        if a.dry_run and a.copy_music:
            print("[dry] la música todavía no está copiada; se omite este chequeo")
        else:
            die("no hay música en el iPod; usa --copy-music o cópiala antes de indexar")

    # Respaldo y limpieza de la base anterior (equivale a 'Initialise Now':
    # se pierden playcounts/valoraciones guardados en la base).
    old = [p for pat in ("database_*.tcd", "tagcache_*.tcd", "database_*.txt", "tagcache_*.txt")
           for p in rb.glob(pat)]
    bk = None
    if old:
        bk = CACHE / "backup" / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
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
    try:
        subprocess.run([str(tool)], cwd=ipod, check=True)
        verify(rb, expected)
    except (subprocess.CalledProcessError, SystemExit) as exc:
        restore_backup(rb, bk)
        if isinstance(exc, subprocess.CalledProcessError):
            die(f"la herramienta de base de datos terminó con error (código {exc.returncode})")
        raise

    print("Sincronizando...")
    os.sync()
    if a.eject and info:
        src_dev = info["source"]
        run(["udisksctl", "unmount", "-b", src_dev])
        subprocess.run(["udisksctl", "power-off", "-b", parent_device(src_dev)], check=False)
    print("Listo. Desconecta el iPod. En Rockbox deja Settings > General Settings > Database > "
          "'Auto Update' en Off (y 'Load to RAM' en Off: el Nano es flash). "
          "Si algo falla, 'Initialise Now' regenera la base en el propio iPod.")


if __name__ == "__main__":
    main()
