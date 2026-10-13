#!/usr/bin/env python3
"""Compare o downloader original e otimizado, com fila fixa e caches frios.

Artefatos e PDFs ficam em DATA_ROOT externo. A cópia original de
camara_annual_csv.R deve ser fornecida em --baseline-source.
"""
import argparse
import collections
import csv
import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import signal
import subprocess
import time
import zipfile

REPO = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def prepare(data_root, baseline, limit, seed, duration):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output = data_root / 'staging' / 'download_benchmarks' / stamp
    output.mkdir(parents=True, exist_ok=False)
    urls, sources = {}, []
    for folder in sorted((data_root / 'raw/camara/annual_csv/proposicoes').glob('*')):
        files = sorted(folder.glob('*.csv'))
        if not files:
            continue
        source = files[0]
        sources.append({'year': folder.name, 'path': str(source), 'sha256': sha256(source)})
        with source.open(encoding='utf-8-sig', newline='') as stream:
            for row in csv.DictReader(stream, delimiter=';'):
                url = (row.get('urlInteiroTeor') or '').strip()
                if url.startswith(('https://', 'http://')):
                    urls.setdefault(url, (row.get('id') or row.get('uri') or '', folder.name))
    items = list(urls.items())
    random.Random(seed).shuffle(items)
    items = items[:limit]
    if not items:
        raise ValueError('Nenhuma URL documental nos CSVs disponíveis.')
    queue = output / 'queue.csv'
    with queue.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream, delimiter=';')
        writer.writerow(['id', 'urlInteiroTeor', 'source_year'])
        for url, (proposition, year) in items:
            writer.writerow([proposition, url, year])
    protocol = {'queue_sha256': sha256(queue), 'seed': seed, 'urls': len(items),
                'source_years': len(sources), 'sources': sources,
                'duration_seconds': duration, 'order': ['base_4', 'optimized_20', 'optimized_40']}
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2))
    (output / 'baseline.R').write_bytes(baseline.read_bytes())
    return output


def run_variant(output, variant, duration):
    workers = {'base_4': 4, 'optimized_20': 20, 'optimized_40': 40}[variant]
    root = output / variant
    root.mkdir(exist_ok=False)
    source = output / 'baseline.R' if variant == 'base_4' else REPO / 'R/download/camara_annual_csv.R'
    (root / 'source.R').write_bytes(source.read_bytes())
    scheduler = REPO / 'R/download/camara_scheduler.R'
    if variant != 'base_4':
        (root / 'scheduler.R').write_bytes(scheduler.read_bytes())
    with (root / 'run.log').open('w') as log:
        process = subprocess.Popen(['Rscript', str(REPO / 'R/download/benchmark_runner.R'),
                                    str(root), str(source), str(output / 'queue.csv'), str(workers)],
                                   cwd=REPO, stdout=log, stderr=subprocess.STDOUT)
        setup_started = time.monotonic()
        try:
            while not (root / 'READY').exists():
                if process.poll() is not None:
                    raise RuntimeError(f'{variant}: falhou antes de iniciar; confira run.log')
                if time.monotonic() - setup_started > 120:
                    raise TimeoutError('Inicialização do worker excedeu 120 s')
                time.sleep(.1)
            start = time.monotonic()
            utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
            (root / 'START').touch()
            next_progress = 30
            while process.poll() is None and time.monotonic() - start < duration:
                elapsed = time.monotonic() - start
                if elapsed >= next_progress:
                    print(f'{variant}: {elapsed:.1f}s', flush=True)
                    next_progress += 30
                time.sleep(min(.2, max(0, duration - elapsed)))
            elapsed = min(duration, time.monotonic() - start)
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(5)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            result = {'variant': variant, 'workers': workers, 'started_at_utc': utc,
                      'window_seconds': elapsed, 'return_code': process.returncode,
                      'source_sha256': sha256(root / 'source.R')}
            if variant != 'base_4':
                result['scheduler_sha256'] = sha256(root / 'scheduler.R')
            (root / 'window.json').write_text(json.dumps(result, indent=2))
            print(json.dumps(result), flush=True)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


def collect(output):
    results = []
    for root in sorted(output.iterdir()):
        if root.name not in ('base_4', 'optimized_20', 'optimized_40') or not (root / 'window.json').exists():
            continue
        result = json.loads((root / 'window.json').read_text())
        blobs = list((root / 'raw/sha256').glob('*/*.bin'))
        checks, total, accepted = collections.Counter(), 0, 0
        parser_checks = {}
        parser_path = root / 'pdf_parser_checks.csv'
        if parser_path.exists():
            with parser_path.open(newline='') as stream:
                parser_checks = {r['sha256']: r for r in csv.DictReader(stream)}
        rows = []
        for path in blobs:
            size = path.stat().st_size
            with path.open('rb') as stream:
                header = stream.read(4096)
                stream.seek(max(0, size - 4096))
                tail = stream.read()
            kind = ('pdf' if header.startswith(b'%PDF-') else
                    'rtf' if header.startswith(b'{\\rtf') else
                    'office' if header.startswith(b'\xd0\xcf\x11\xe0') else
                    'zip' if header.startswith(b'PK\x03\x04') else 'unknown')
            actual_hash = sha256(path)
            valid = actual_hash == path.stem and kind != 'unknown'
            if kind == 'pdf':
                valid = valid and b'%%EOF' in tail
                if parser_checks:
                    valid = valid and parser_checks.get(path.stem, {}).get('pdf_parser_valid') == 'TRUE'
            if kind == 'zip':
                try:
                    with zipfile.ZipFile(path) as archive:
                        valid = valid and archive.testzip() is None
                except zipfile.BadZipFile:
                    valid = False
            checks['hash_mismatch'] += actual_hash != path.stem
            checks[kind] += 1
            if valid:
                accepted += 1
                total += size
            rows.append({'sha256': path.stem, 'bytes': size, 'kind': kind,
                         'hash_valid': actual_hash == path.stem, 'structurally_valid': valid})
        with (root / 'blob_checks.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['sha256', 'bytes', 'kind', 'hash_valid', 'structurally_valid'])
            writer.writeheader()
            writer.writerows(rows)
        statuses = {}
        for path in sorted((root / 'stage').glob('annual_document_status_*/chunk_*.csv')):
            with path.open(newline='') as stream:
                for row in csv.DictReader(stream):
                    statuses[row['requested_url']] = row['status']
        # O diário tem as conclusões após o último checkpoint; ignore apenas a
        # última linha incompleta de uma interrupção, sem silenciar outras falhas.
        for path in sorted((root / 'stage').glob('annual_document_status_*/chunk_*.csv.events.jsonl')):
            lines = path.read_text().splitlines()
            for index, line in enumerate(lines):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    if index == len(lines) - 1:
                        continue
                    raise
                statuses[event['url']] = event['result']['status']
        result.update({'blobs_persisted': len(blobs), 'valid_unique_files': accepted,
                       'valid_bytes': total, 'files_per_second': accepted / result['window_seconds'],
                       'MB_per_second': total / 1e6 / result['window_seconds'], 'format_counts': checks,
                       'completed_url_statuses': dict(collections.Counter(statuses.values()))})
        results.append(result)
    baseline = next((r for r in results if r['variant'] == 'base_4'), None)
    for result in results:
        if baseline and baseline['files_per_second']:
            result['speedup_files_vs_base'] = result['files_per_second'] / baseline['files_per_second']
            result['speedup_bytes_vs_base'] = result['MB_per_second'] / baseline['MB_per_second']
    (output / 'results.json').write_text(json.dumps(results, indent=2))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=os.environ.get('DATA_ROOT'))
    parser.add_argument('--baseline-source', type=Path)
    parser.add_argument('--reuse-run', type=Path)
    parser.add_argument('--collect-only', type=Path)
    parser.add_argument('--duration', type=float, default=180)
    parser.add_argument('--queue-size', type=int, default=50000)
    parser.add_argument('--seed', type=int, default=20261008)
    parser.add_argument('--variants', nargs='+', choices=['base_4', 'optimized_20', 'optimized_40'],
                        default=['base_4', 'optimized_20', 'optimized_40'])
    parser.add_argument('--pause-pid', type=int, help='PID de uma coleta autorizada a pausar durante as medições')
    args = parser.parse_args()
    if args.collect_only:
        print(json.dumps(collect(args.collect_only.resolve()), indent=2))
        return
    if args.duration <= 0 or args.queue_size <= 0:
        parser.error('Duração e tamanho da fila devem ser positivos.')
    if args.reuse_run:
        output = args.reuse_run.resolve()
        protocol = json.loads((output / 'protocol.json').read_text())
        if sha256(output / 'queue.csv') != protocol['queue_sha256']:
            raise ValueError('Hash da fila diverge do protocolo.')
    else:
        if not args.data_root or not args.baseline_source:
            parser.error('Informe --data-root e --baseline-source, ou --reuse-run.')
        data_root = args.data_root.expanduser().resolve()
        if data_root == REPO or REPO in data_root.parents:
            raise ValueError('DATA_ROOT precisa ficar fora do checkout.')
        output = prepare(data_root, args.baseline_source, args.queue_size, args.seed, args.duration)
    print(f'BENCHMARK_ROOT {output}', flush=True)
    if args.pause_pid:
        os.kill(args.pause_pid, signal.SIGSTOP)
    try:
        for variant in args.variants:
            run_variant(output, variant, args.duration)
    finally:
        if args.pause_pid:
            os.kill(args.pause_pid, signal.SIGCONT)
    print(json.dumps(collect(output), indent=2))


if __name__ == '__main__':
    main()
