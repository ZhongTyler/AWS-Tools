"""Source-bound literal boundaries; undeclared text retains the legacy guard."""
from collections import Counter
import hashlib
import re

VERSION = 'literal-boundaries-v2'
ASCII_WORD = re.compile(r'[A-Za-z0-9_.-]')
NUMBER_WORD = re.compile(r'[0-9零〇一二两三四五六七八九十百千万亿]')


def counter_factory(items, runs, inventory, legacy):
    if (not isinstance(inventory, dict) or inventory.get('contract_version') != VERSION
            or inventory.get('status') != 'maintenance_reviewed_literal_boundaries'):
        raise ValueError('unreviewed_literal_boundaries')
    field = inventory.get('source_id')
    sources = {row['id']: row['text'] for row in items if row['id'] in runs}
    if field not in sources or hashlib.sha256(sources[field].encode()).hexdigest() != inventory.get('source_text_sha256'):
        raise ValueError('literal_source_changed')
    literals, numbers = inventory.get('literal_counts'), inventory.get('numbers')
    if (not isinstance(literals, dict) or not literals or not isinstance(numbers, dict)
            or any(not isinstance(k, str) or not k or len(k) > 512 or '\n' in k
                   or type(v) is not int or v < 1 for k,v in [*literals.items(), *numbers.items()])):
        raise ValueError('invalid_literal_inventory')
    if set(literals) & set(numbers):
        raise ValueError('ambiguous_literal_inventory')
    for value, count in [*literals.items(), *numbers.items()]:
        if sources[field].count(value) != count:
            raise ValueError('literal_count_does_not_match_source')
    # Only the declared field gets this boundary interpretation. All other fields
    # and every undeclared Unicode path retain the original conservative matcher.
    identifier = r'(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)+(?![A-Za-z0-9_])'
    residual = re.compile(legacy.pattern.replace(
        r'\b[A-Za-z][A-Za-z0-9]*(?:[_-][A-Za-z0-9]+)+\b', identifier), legacy.flags)
    ordered = sorted([*literals, *numbers], key=lambda x: (-len(x), x))
    def counter(name, text):
        if name != field:
            return Counter(legacy.findall(text))
        result, covered = Counter(), [False] * len(text)
        # Count original literal spellings, including overlapping nested names,
        # independently from masking so adding/removing occurrences cannot hide.
        for value in ordered:
            result['declared:' + value] = text.count(value)
        for value in ordered:
            for match in re.finditer(re.escape(value), text):
                start,end = match.span()
                if any(covered[start:end]):
                    continue
                previous = text[start-1] if start else ''
                following = text[end] if end < len(text) else ''
                boundary = NUMBER_WORD if value in numbers else None
                # The source spelling is fixed by its reviewed hash; old Chinese
                # prose adjacency is not guessed. A changed candidate must expose
                # each unmasked declaration as an explicitly delimited whole value.
                # Long declarations already cover their nested shorter names.
                def separated(char):
                    return not char or char.isspace() or char in '，。；：！？、（）【】《》“”‘’「」『』〈〉〔〕［］｛｝,;:!?<>()[]{}"\'`'
                connected = ((previous and (boundary.fullmatch(previous) or previous in '/\\'))
                             or (following and (boundary.fullmatch(following) or following in '/\\'))) if boundary else not (separated(previous) and separated(following))
                if text != sources[field] and connected:
                    result['connected:' + value] += 1
                for i in range(start,end):
                    covered[i] = True
        remaining = ''.join(' ' if covered[i] else c for i,c in enumerate(text))
        result.update(residual.findall(remaining))
        return result
    return counter
