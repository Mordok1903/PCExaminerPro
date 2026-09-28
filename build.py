"""
Script de compilación de PC Examiner Pro a .exe
Ejecutar con: python build.py
"""

import subprocess
import sys
import os

def build():
    print("=" * 60)
    print("PC Examiner Pro - Compilando a .exe")
    print("=" * 60)

    # Ruta del pyinstaller
    pyinstaller_paths = [
        "pyinstaller",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), 
                     r"Packages\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0"
                     r"\LocalCache\local-packages\Python312\Scripts\pyinstaller.exe"),
    ]

    pyinstaller_cmd = None
    for path in pyinstaller_paths:
        try:
            result = subprocess.run([path, "--version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                pyinstaller_cmd = path
                break
        except:
            continue

    if not pyinstaller_cmd:
        # Usar python -m PyInstaller como fallback
        pyinstaller_cmd = None

    print("\n[1/3] Preparando compilacion...")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                    # Un solo .exe
        "--windowed",                   # Sin consola (GUI app)
        "--name", "PCExaminerPro",      # Nombre del ejecutable
        "--clean",                      # Limpiar cache
        "--uac-admin",                  # Solicitar permisos de admin
        "--noconfirm",                  # Auto-confirmar sobrescritura
        "main.py"
    ]

    print("[2/3] Ejecutando PyInstaller...")
    print(f"Comando: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))

    if result.returncode == 0:
        print("\n" + "=" * 60)
        print("COMPILACION EXITOSA!")
        print("El archivo .exe se encuentra en: dist/PCExaminerPro.exe")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("ERROR en la compilacion. Revisa los mensajes anteriores.")
        print("=" * 60)
        sys.exit(1)

if __name__ == "__main__":
    build()
