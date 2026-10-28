"""quickdic.db → quickdic.db.gz + version.json (앱이 확인하는 버전 정보)"""

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import sys


def main(db_path: str = "quickdic.db"):
    gz_path = db_path + ".gz"
    with open(db_path, "rb") as src, gzip.open(gz_path, "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst, 1 << 20)

    sha = hashlib.sha256()
    with open(gz_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha.update(chunk)

    con = sqlite3.connect(db_path)
    meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
    con.close()

    info = {
        "version": meta.get("version"),
        "schema": int(meta.get("schema", 1)),
        "built_at": meta.get("built_at"),
        "file": os.path.basename(gz_path),
        "gz_size": os.path.getsize(gz_path),
        "gz_sha256": sha.hexdigest(),
        "db_size": os.path.getsize(db_path),
        "en_source": meta.get("en_source", ""),
        "ko_source": meta.get("ko_source", ""),
        "kodict_source": meta.get("kodict_source", ""),
        "counts": {k[6:]: int(v) for k, v in meta.items() if k.startswith("count_")},
    }
    with open("version.json", "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:])
