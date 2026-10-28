"""Generate private configuration for a fresh installation; never starts services."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets

ROOT = Path(__file__).resolve().parent


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    if os.name != "nt":
        path.chmod(0o600)


def json_text(value):
    return json.dumps(value, indent=2) + "\n"


def configure(root, config_path, role):
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if config.get("schema_version") != 1:
        raise ValueError("schema_version deve ser 1")
    for key in ("linux_ip", "windows_ip"):
        if ipaddress.ip_address(config[key]).version != 4:
            raise ValueError("Use enderecos IPv4 privados alcancaveis entre as maquinas")
    for key in ("web_port", "postgres_port", "bridge_port"):
        if type(config[key]) is not int or not 1024 <= config[key] <= 65535:
            raise ValueError(f"Porta invalida: {key}")
    if len({config['web_port'], config['postgres_port'], 8770}) != 3:
        raise ValueError("Portas Linux devem ser distintas (API usa 8770)")
    for key in ("database_password", "postgres_admin_password", "bridge_token"):
        if not config.get(key):
            if role != "linux":
                raise ValueError("Gere primeiro no Linux e transfira a configuracao privada")
            config[key] = secrets.token_hex(32)
        if not re.fullmatch(r"[a-zA-Z0-9_-]{32,128}", config[key]):
            raise ValueError(f"{key}: use 32 a 128 letras, numeros, _ ou -")
    data = root / "data"
    provisioning = data / "provisioning"
    targets = [data / "database.json"]
    if role == "windows":
        targets += [data / "timestral.json", data / "mt5_bridge.token", data / "multi_asset.json"]
    else:
        targets += [provisioning / "compose.json", provisioning / "init.sql", provisioning / "nginx.conf"]
    if any(p.exists() for p in targets):
        raise ValueError("Configuracao existente: use clone novo. Nenhum arquivo foi substituido.")
    # Preserve generated secrets for the Windows host and disaster recovery.
    write(config_path, json_text(config))
    linux = config['linux_ip']
    windows = config['windows_ip']
    db_port = config['postgres_port']
    web_port = config['web_port']
    bridge_port = config['bridge_port']
    password = config['database_password']
    write(data / "database.json", json_text({"database_url":
          f"postgresql://agente_trader_app:{password}@{linux}:{db_port}/agente_trader"}))
    if role == "windows":
        model = json.loads((root / "config/timestral.example.json").read_text())
        model.update(python=str(root / ".venv-timestral/Scripts/python.exe"),
                     cache_dir=str(data / "models/timestral"))
        write(data / "timestral.json", json_text(model))
        write(data / "mt5_bridge.token", config['bridge_token'] + "\n")
        write(data / "multi_asset.json", (root / "config/multi_asset.example.json").read_text())
        print(f"Windows configurado. Defina AURELIA_MT5_BRIDGE_HOST={windows} e AURELIA_MT5_BRIDGE_PORT={bridge_port} no usuario das tarefas.")
        return
    nginx = (root / "deploy/vm/nginx-chart.conf").read_text(encoding="utf-8")
    nginx = nginx.replace("192.168.97.221:8097", f"{linux}:{web_port}")
    nginx = nginx.replace("192.168.200.1:8769", f"{windows}:{bridge_port}")
    nginx = nginx.replace("${MT5_BRIDGE_TOKEN}", config['bridge_token'])
    write(provisioning / "nginx.conf", nginx)
    write(provisioning / "init.sql",
          f"CREATE ROLE agente_trader_app LOGIN PASSWORD '{password}';\n"
          "CREATE DATABASE agente_trader OWNER agente_trader_app;\n")
    if os.name != "nt":
        # Docker mounts this file directly; postgres must read it as its own UID.
        # Keep the parent private so other host users cannot read the secret.
        provisioning.chmod(0o700)
        (provisioning / "init.sql").chmod(0o644)
    compose = {
        "name": "agente-trader-fresh",
        "services": {
            "db": {
                "image": "postgres:16", "restart": "unless-stopped",
                "environment": {"POSTGRES_PASSWORD": config['postgres_admin_password']},
                "ports": [f"{linux}:{db_port}:5432"],
                "volumes": ["postgres-data:/var/lib/postgresql/data",
                            f"{provisioning.as_posix()}/init.sql:/docker-entrypoint-initdb.d/01-app.sql:ro"],
                "healthcheck": {"test": ["CMD-SHELL", "pg_isready -U postgres -d agente_trader"],
                                "interval": "5s", "timeout": "5s", "retries": 20}},
            "api": {
                "build": {"context": root.as_posix(), "dockerfile": "deploy/fresh/Dockerfile"},
                "network_mode": "host", "restart": "unless-stopped",
                "depends_on": {"db": {"condition": "service_healthy"}},
                "environment": {"AGENTE_TRADER_PUBLIC_URL": f"http://{linux}:{web_port}"},
                "volumes": [f"{data.as_posix()}:/app/data"]},
            "web": {
                "image": "nginx:1.28-alpine", "network_mode": "host",
                "restart": "unless-stopped", "depends_on": ["api"],
                "volumes": [f"{(root / 'static').as_posix()}:/usr/share/nginx/html:ro",
                            f"{provisioning.as_posix()}/nginx.conf:/etc/nginx/conf.d/default.conf:ro"]}},
        "volumes": {"postgres-data": {}}}
    write(provisioning / "compose.json", json_text(compose))
    print("Linux configurado. Revise e execute: docker compose -f data/provisioning/compose.json up -d --build")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", required=True, choices=("linux", "windows"))
    parser.add_argument("--config", type=Path, default=ROOT / "config/new-environment.local.json")
    args = parser.parse_args()
    configure(ROOT, args.config.resolve(), args.role)


if __name__ == "__main__":
    main()
