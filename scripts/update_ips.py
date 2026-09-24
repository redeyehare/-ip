#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# 国家代码映射中文名字典
COUNTRY_MAP = {
    "HK": "香港",
    "TW": "台湾",
    "MO": "澳门",
    "CN": "中国",
    "JP": "日本",
    "KR": "韩国",
    "SG": "新加坡",
    "US": "美国",
    "CA": "加拿大",
    "GB": "英国",
    "UK": "英国",
    "DE": "德国",
    "FR": "法国",
    "NL": "荷兰",
    "AU": "澳大利亚",
    "RU": "俄罗斯",
    "IN": "印度",
    "MY": "马来西亚",
    "TH": "泰国",
    "VN": "越南",
    "PH": "菲律宾",
    "ID": "印度尼西亚",
    "AE": "阿联酋",
    "BR": "巴西",
    "TR": "土耳其"
}

# 常见国家中文名称集合
COMMON_COUNTRIES = [
    "香港", "台湾", "澳门", "日本", "韩国", "新加坡", "美国", "加拿大",
    "英国", "德国", "法国", "荷兰", "澳大利亚", "俄罗斯", "印度", "马来西亚"
]

# 内存 IP 国家信息缓存
GEO_CACHE = {}


import ssl

# 忽略 SSL 证书与吊销校验上下文
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE


def fetch_url(url):
    """抓取远程 URL 文本内容，发生异常静默返回空"""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=15, context=SSL_CONTEXT) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def query_country(ip):
    """根据 IP 查询国家中文名称，内置缓存与静默容错"""
    if ip in GEO_CACHE:
        return GEO_CACHE[ip]
    try:
        api_url = f"https://ipwho.is/{ip}"
        req = urllib.request.Request(
            api_url,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=2, context=SSL_CONTEXT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            code = data.get("country_code", "")
            if code in COUNTRY_MAP:
                result = COUNTRY_MAP[code]
                GEO_CACHE[ip] = result
                return result
    except Exception:
        pass
    GEO_CACHE[ip] = ""
    return ""


def parse_and_format_nodes(raw_text, max_needed):
    """解析源文本，提取合法 IP 和端口，仅对所需数量进行国家查询并按要求重命名"""
    if not raw_text:
        return []

    lines = raw_text.splitlines()
    candidates = []

    # 匹配 IP 或 域名:端口 模式
    line_pattern = re.compile(r"^([a-zA-Z0-9\.\-]+):(\d+)(?:#(.*))?$")
    ipv4_pattern = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 跳过包含时间戳或说明性质的表头与表尾行
        if "|" in line and "BestCF" in line:
            continue

        match = line_pattern.match(line)
        if match:
            host = match.group(1).strip()
            port = match.group(2).strip()
            raw_remark = match.group(3) if match.group(3) else ""
            candidates.append((host, port, raw_remark))
            # 达到所需最大节点数时提前截断，减少无效网络请求
            if len(candidates) >= max_needed:
                break

    if not candidates:
        return []

    # 提取需要查询 GeoIP 的 IPv4 地址
    ips_to_query = [h for h, _, _ in candidates if ipv4_pattern.match(h) and h not in GEO_CACHE]
    if ips_to_query:
        try:
            with ThreadPoolExecutor(max_workers=10) as executor:
                list(executor.map(query_country, ips_to_query))
        except Exception:
            pass

    results = []
    for host, port, raw_remark in candidates:
        country = ""
        # 优先读取 IP 查询所得国家
        if host in GEO_CACHE and GEO_CACHE[host]:
            country = GEO_CACHE[host]
        else:
            # 尝试从原有备注中匹配已知国家名
            for c in COMMON_COUNTRIES:
                if c in raw_remark:
                    country = c
                    break

        # 格式化节点名称为：国家+ip（如：香港 104.17.159.205）
        if country:
            node_name = f"{country} {host}"
        else:
            node_name = host

        results.append(f"{host}:{port}#{node_name}")

    return results


def process_source(source_conf, base_dir):
    """处理单个优选源，严格验证配置字段禁止兜底，切分并写入文件"""
    # 严格检查配置字段，任何字段缺失则直接跳过，禁止兜底
    if "url" not in source_conf:
        return
    if "folder" not in source_conf:
        return
    if "ips_per_file" not in source_conf:
        return
    if "file_count" not in source_conf:
        return

    url = source_conf["url"]
    folder = source_conf["folder"]
    ips_per_file = source_conf["ips_per_file"]
    file_count = source_conf["file_count"]

    if not isinstance(url, str) or not url.strip():
        return
    if not isinstance(folder, str) or not folder.strip():
        return
    if not isinstance(ips_per_file, int) or ips_per_file <= 0:
        return
    if not isinstance(file_count, int) or file_count <= 0:
        return

    # 计算总共需要的节点数
    total_needed = ips_per_file * file_count

    # 拉取并解析节点
    raw_text = fetch_url(url.strip())
    nodes = parse_and_format_nodes(raw_text, total_needed)

    # 准备目标文件夹
    target_dir = os.path.join(base_dir, folder.strip())
    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception:
        return

    # 按照设定切分并写入文件，生成 1.txt, 2.txt ...
    for file_index in range(1, file_count + 1):
        start_idx = (file_index - 1) * ips_per_file
        end_idx = start_idx + ips_per_file
        chunk = nodes[start_idx:end_idx]

        if not chunk:
            break

        file_path = os.path.join(target_dir, f"{file_index}.txt")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(chunk) + "\n")
        except Exception:
            pass


def main():
    """主程序入口，读取配置文件并逐个执行处理"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config.json")

    if not os.path.exists(config_path):
        return

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            sources = json.load(f)
    except Exception:
        return

    if not isinstance(sources, list):
        return

    for source_conf in sources:
        if isinstance(source_conf, dict):
            process_source(source_conf, base_dir)


if __name__ == "__main__":
    main()
