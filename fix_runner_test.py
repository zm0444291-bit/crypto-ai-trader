#!/usr/bin/env python3
"""Fix _build_cycle_inputs return value unpacking in test file."""

path = '/Users/zihanma/Desktop/crypto-ai-trader/tests/unit/test_runtime_runner.py'
with open(path) as f:
    content = f.read()

old = 'inputs = _build_cycle_inputs('
new = 'inputs, _account_equity, _day_start_equity = _build_cycle_inputs('
count = content.count(old)
print(f'Found {count} occurrences of "{old}"')
new_content = content.replace(old, new)
with open(path, 'w') as f:
    f.write(new_content)
remaining = new_content.count(old)
print(f'Remaining after fix: {remaining}')
