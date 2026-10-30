import platform
from pathlib import Path
from subprocess import run
from shutil import copy
from platformdirs import user_data_path

DATA_DIR = user_data_path("mid", appauthor=False)
LIB_NAME = "mid.lib" if platform.system() == "Windows" else "libmid.a"
LIB_FILE = DATA_DIR/LIB_NAME

def install():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    run(["cmake", "-S", "runtime", "-B", "runtime/build"], check=False)
    run(["make", "-C", "runtime/build"], check=False)
    copy(Path("runtime/build")/LIB_NAME, LIB_FILE)
