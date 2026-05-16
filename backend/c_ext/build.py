import os
import subprocess


def build():
    base = os.path.dirname(__file__)
    subprocess.run(["gcc", "-O3", "-shared", "-fPIC", "-o", os.path.join(base, "price_map.so"), os.path.join(base, "price_map.c")], check=True)
    subprocess.run(["gcc", "-O3", "-shared", "-fPIC", "-o", os.path.join(base, "detection.so"), os.path.join(base, "detection.c")], check=True)


if __name__ == "__main__":
    build()
