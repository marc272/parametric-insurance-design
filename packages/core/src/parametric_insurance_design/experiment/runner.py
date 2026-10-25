"""Run executor (SPEC §4.2, thesis issues C3, C5).

Owner: MAR-64. Executes one configured run: EventSet (plus noise) -> for each
scope x objective: ``problem.build_problems`` -> ``solve.solve`` ->
``evaluate.kpis`` -> rows of the ``records`` tables. A failed solve becomes a
``runs`` row with its status and error; it is never skipped.
"""
