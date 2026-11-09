#!/usr/bin/env bash
set -euo pipefail
OUT=${1:?Uso: bash coleta_ambiente.sh diretorio [interface]}
IFACE=${2:-}
mkdir -p -- "$OUT"
capture() {
    local name=$1
    shift
    { printf 'Comando:'; printf ' %q' "$@"; printf '\n'; "$@"; } >"$OUT/$name.txt" 2>&1 || printf '\nConsulta indisponivel (ferramenta ou permissao).\n' >>"$OUT/$name.txt"
}
capture cpu lscpu
capture ram free -h
capture kernel uname -a
capture os cat /etc/os-release
capture compiler gcc --version
capture revision git -C "$(dirname -- "$0")/.." rev-parse HEAD
capture changes git -C "$(dirname -- "$0")/.." status --short
capture addresses ip addr
capture routes ip route
capture tcp sysctl net.ipv4.tcp_congestion_control net.ipv4.tcp_rmem net.ipv4.tcp_wmem net.core.rmem_max net.core.wmem_max
capture virtualization cat /proc/version
if [[ -n "$IFACE" ]]; then
    capture interface ethtool "$IFACE"
    capture wireless iw dev "$IFACE" link
fi
if [[ ! -e "$OUT/notas.txt" ]]; then
    printf 'Conexao (loopback/cabo/Wi-Fi):\nInterface:\nCabo e velocidade:\nRoteador/switch:\nCondicoes da rede e outras cargas:\nFlags: -O2 -Wall -Wextra -pthread\n' >"$OUT/notas.txt"
fi
