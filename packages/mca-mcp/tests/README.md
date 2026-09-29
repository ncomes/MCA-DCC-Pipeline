# Running these

```
python tests/test_core.py      no Maya needed - 36 checks
test_live.bat 2025             a real Maya, end to end
```

`test_live.bat` writes everything it printed to `tests/last_run.log` as well as the console,
so the run can be read back afterwards — including by an assistant that has the repo folder
but not the machine.
