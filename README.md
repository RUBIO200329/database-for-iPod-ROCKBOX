<img width="640" height="360" alt="rockDB-nanoTOOL" src="https://github.com/user-attachments/assets/1a7cfcec-0494-4014-b087-6f996c20da6b" />


🇪🇸 Español

Generación de base de datos: Compila y ejecuta la herramienta oficial de Rockbox para crear los archivos tagcache (.tcd) compatibles con el iPod nano 3G. 

Autodetección del iPod: Localiza automáticamente el punto de montaje del iPod buscando unidades con formato FAT32 que contengan la carpeta /.rockbox.   

Compilación de herramientas: Descarga del repositorio de GitHub la fuente de Rockbox y compila el ejecutable database.ipodnano3g localmente.   

Copia de música opcional: Permite sincronizar directorios locales de música directamente hacia la carpeta /Music del iPod usando rsync.   

Reescalado de carátulas: Incluye una opción (--art) para ajustar el tamaño de las imágenes ID3/mjpeg incrustadas en los MP3 mediante ffmpeg sin alterar el audio.   

Contención de errores y respaldo: Crea copias de seguridad de las bases de datos anteriores en .cache antes de procesar la nueva y las restaura si el proceso falla.   

Validación de ficheros: Analiza los cabezales binarios (magics) y la integridad de los índices database_idx.tcd generados para confirmar su validez.   C

Conteo de pistas: Escanea la estructura del almacenamiento para contabilizar archivos de audio soportados (MP3, FLAC, M4A, etc.) y verificar la indexación.   

Extracción segura: Dispone de un flag opcional (--eject) para desmontar la partición y apagar eléctricamente el dispositivo de forma segura mediante udisksctl.   

Pruebas en seco: Soporta una opción de simulación (--dry-run) para previsualizar los comandos y acciones a realizar sin alterar la memoria del iPod.   🇬🇧 

🇬🇧 English

Database Generation: Compiles and runs the official Rockbox tool to create tagcache (.tcd) files compatible with the iPod nano 3G.   iPod 

Autodetection: Automatically detects the iPod's mount point by searching for FAT32-formatted drives containing the /.rockbox folder.   

Tool Compilation: Clones the Rockbox source from the GitHub repository and locally compiles the database.ipodnano3g executable.   

Optional Music Copying: Allows syncing local music directories directly to the iPod's /Music folder using rsync.   

Cover Art Resizing: Includes an option (--art) to resize embedded ID3/mjpeg cover art in MP3 files via ffmpeg without altering the audio.   

Error Handling & Backup: Backs up existing databases to .cache before generating a new one and restores them if the process fails.   

File Validation: Analyzes binary headers (magics) and the integrity of generated database_idx.tcd indices to confirm validity.   

Track Counting: Scans the storage structure to count supported audio files (MP3, FLAC, M4A, etc.) and verify indexing.   

Safe Ejection: Provides an optional flag (--eject) to unmount the partition and safely power off the device using udisksctl.   

Dry Run Support: Supports a simulation option (--dry-run) to preview commands and actions without modifying the iPod's memory.   



Note -----> Only tested in iPod Nano 3rd GEN, due the poor CPU and RAM capacity of this device


CREDITS TO:

ROCKBOX PORT;
https://github.com/giek2000/Nano3Rockbox

CLAUDE and GEMINI;
For helping to make script and solve issues
