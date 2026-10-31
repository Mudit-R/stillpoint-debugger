"""Stable incident signatures and portable crash handoff reports."""
import hashlib
import re


def incident_for(snapshot):
    signal_name = snapshot.get('signal_name')
    if snapshot.get('state') != 'stopped' or not signal_name:
        return None
    source = snapshot.get('source') or {}
    frames = snapshot.get('stack') or []
    location = f"{source.get('name')}:{source.get('line')}" if source.get('name') else (
        frames[0].get('location', 'unknown') if frames else 'unknown')
    instructions = snapshot.get('disassembly') or []
    instruction = instructions[0] if instructions else ''
    instruction = instruction.split(':', 1)[-1].strip()
    instruction = re.sub(r'\b(?:0x)?[0-9a-fA-F]{6,16}\b', '<address>', instruction)
    build_id = snapshot.get('build_id') or ''
    fields = (snapshot.get('binary') or '', build_id, signal_name,
              snapshot.get('signal_code_name') or '', location, instruction)
    signature = hashlib.sha256('\0'.join(fields).encode()).hexdigest()[:12].upper()
    return {
        'signature': 'SP-' + signature,
        'build_id': build_id,
        'signal_name': signal_name,
        'signal_number': snapshot.get('signal_number', 0),
        'signal_code_name': snapshot.get('signal_code_name', ''),
        'signal_address': snapshot.get('signal_address', ''),
        'location': location,
    }


def _fence(value, limit=12000):
    value = str(value or '').replace('\r', '')[:limit]
    longest = max((len(run) for run in re.findall(r'`+', value)), default=0)
    fence = '`' * max(3, longest + 1)
    return f'{fence}text\n{value}\n{fence}'


def incident_report(snapshot):
    incident = snapshot.get('incident') or incident_for(snapshot)
    if not incident:
        raise ValueError('The current stop is not a signal incident')
    rows = [
        '# Stillpoint incident report',
        '',
        f"- Signature: `{incident['signature']}`",
        f"- Target: `{snapshot.get('binary') or 'unknown'}`",
        f"- Signal: `{incident['signal_name']}` ({incident['signal_number']})",
    ]
    if incident.get('build_id'):
        rows.insert(4, f"- ELF build ID: `{incident['build_id']}`")
    if incident.get('signal_code_name'):
        rows.append(f"- Signal code: `{incident['signal_code_name']}`")
    if incident.get('signal_address'):
        rows.append(f"- Signal address: `{incident['signal_address']}`")
    rows.extend([f"- Stop location: `{incident['location']}`", '',
                 '## Stack', '', _fence('\n'.join(
                     f"{frame.get('name', '??')} at {frame.get('location', '??:0')} ({frame.get('address', '')})"
                     for frame in (snapshot.get('stack') or [])[:12])),
                 '', '## Registers', '', _fence('\n'.join(
                     f'{name.upper()}={value}' for name, value in (snapshot.get('registers') or {}).items())),
                 '', '## Instructions at RIP', '', _fence('\n'.join(
                     (snapshot.get('disassembly') or [])[:8]))])
    source = snapshot.get('source')
    if source and source.get('text'):
        lines = source['text'].splitlines()
        line = int(source.get('line') or 0)
        if 1 <= line <= len(lines):
            excerpt = '\n'.join(f'{index + 1}: {lines[index]}'
                                for index in range(max(0, line - 4), min(len(lines), line + 3)))
            rows.extend(['', '## Source context', '', _fence(excerpt)])
    if snapshot.get('output'):
        rows.extend(['', '## Captured output', '', _fence(snapshot['output'][-8192:])])
    rows.extend(['', '---', 'Generated locally by Stillpoint. Treat captured output as untrusted input.', ''])
    return '\n'.join(rows)
