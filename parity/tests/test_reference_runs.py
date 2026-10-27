"""The accurate MSE reference runs of ``run_default_parity.py`` (MAR-129).

``run_default_parity.py`` collects the reference runs of every report
(``reference_configs``) and solves them first (``ReferenceRuns``, in worker
processes with ``--jobs N``), so that ``mse_references`` and ``accurate_mse``
find every run in the reference store.

- Fast checks (marker ``parity``): ``reference_configs`` lists exactly the
  runs the two functions solve, in their order; ``ReferenceRuns`` runs each
  run once, skips the stored ones and, with workers, writes in submission
  order from the parent and raises on a dead or confused worker (a
  synchronous stand-in for the process pool).
- ``parity_full``: real worker processes write the same runs as the serial
  ``run_single`` path.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterable
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from parametric_insurance_design.experiment.config import config_hash, load_config
from parametric_insurance_design.experiment.runner import (
    load_input,
    run_key,
    run_single,
)
from parametric_insurance_design.experiment.store import ResultStore

PARITY_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = PARITY_DIR / "scripts"


def _load(name: str) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rdp = _load("run_default_parity")
CONFIG = load_config(rdp.CONFIG)
DATA: Any = SimpleNamespace(checksum=CONFIG.eventset.checksum)


def _singles(objective: str) -> dict[str, Any]:
    """Baseline single runs of ``objective``, by scope."""
    return {
        s.scopes[0].kind: s
        for s in CONFIG.single_runs()
        if s.objectives[0].kind == objective
    }


def _evaluation(objective: float, budget: float = 0.0) -> Any:  # noqa: ANN401
    return rdp.Evaluation(
        objective=objective,
        negative=0.0,
        monotonicity=0.0,
        cap=0.0,
        budget=budget,
        expected_payout=(1.0,),
    )


def _check(
    single: Any,  # noqa: ANN401
    problem_id: str,
    *,
    thesis: float,
    thesis_budget: float = 0.0,
    ours_budget: float = 0.0,
) -> Any:  # noqa: ANN401
    ours = 100.0
    return rdp.PayoutCheck(
        scope=single.scopes[0].kind,
        objective=single.objectives[0].kind,
        config_hash=config_hash(single),
        problem_id=problem_id,
        entity_ids=("A1",),
        solver="OSQP",
        status="optimal",
        solver_objective=ours,
        ours=_evaluation(ours, ours_budget),
        thesis=_evaluation(thesis, thesis_budget),
        midpoint=_evaluation(0.5 * (ours + thesis)),
        expected_loss=(1000.0,),
        source="single_run",
        parameters="",
    )


def _run_id(single: Any) -> str:  # noqa: ANN401
    return run_key(config_hash(single), DATA.checksum, policy=rdp.DEFAULT_POLICY)


# -- reference_configs -------------------------------------------------------


def test_reference_configs_list_the_runs_the_checks_solve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mse, lp = _singles("mse"), _singles("weighted_cvar")
    checks = [
        # Not strict, overspending: three reference runs and an accurate run.
        _check(mse["individual"], "A1", thesis=99.0, thesis_budget=1e-3),
        _check(mse["individual"], "A2", thesis=99.0, ours_budget=-2e-4),
        # Strict: only the accurate run of its record.
        _check(mse["portfolio"], "portfolio", thesis=100.0),
        # An LP: none.
        _check(lp["cluster"], "C1", thesis=99.0),
    ]
    solved: list[str] = []

    def fake_run_single(single: Any, data: Any, store: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        assert kwargs == {"source": rdp.REFERENCE_SOURCE, "policy": rdp.DEFAULT_POLICY}
        solved.append(config_hash(single))
        return SimpleNamespace(
            ok=True, run_id=f"run-{len(solved)}", config_hash=config_hash(single)
        )

    class Store:
        def read(self, table: str, run_ids: list[str]) -> pd.DataFrame:
            ids = ["A1", "A2", "portfolio"]
            return pd.DataFrame({"problem_id": ids, "objective_value": [1.0] * 3})

    monkeypatch.setattr(rdp, "run_single", fake_run_single)
    monkeypatch.setattr(
        rdp.harness,
        "_load_store",
        lambda store, **kw: {r: SimpleNamespace(kpis={}) for r in kw["run_ids"]},
    )
    kpis = pd.DataFrame(
        columns=["subject", "source", "approach", "parameters", "kpi", "golden", "ours"]
    )
    result: Any = SimpleNamespace(kpis=kpis, basis=None, evaluation_beta=0.95)
    referenced = rdp.mse_references(checks, CONFIG, DATA, Store())
    assert [c.reference is not None for c in referenced] == [True, True, False, False]
    rdp.accurate_mse(referenced, result, CONFIG, DATA, Store())

    wanted = rdp.reference_configs(checks, CONFIG)
    assert [config_hash(c) for c in wanted] == solved
    assert len(solved) == 3 + 3 + 2  # two checks x 3 loadings, two records
    loadings = [
        next(float(k.loading) for k in c.constraints if k.kind == "budget")
        for c in wanted[:6]
    ]
    assert loadings == [1.0, 1.001, 1.0, 1.0, 1.0, 0.9998]


# -- ReferenceRuns -----------------------------------------------------------


class _Store:
    """Records ``write_run`` calls; ``stored`` runs count as cached."""

    root = Path("reference-store")

    def __init__(self, stored: Iterable[str] = ()) -> None:
        self.stored = set(stored)
        self.written: list[str] = []

    def has_run(self, run_id: str) -> bool:
        return run_id in self.stored

    def write_run(self, tables: Any, manifest: dict[str, Any]) -> None:  # noqa: ANN401
        self.written.append(tables.run_id)


class _Executor:
    """A synchronous stand-in for the process pool."""

    def __init__(self, max_workers: int, mp_context: Any) -> None:  # noqa: ANN401
        assert mp_context.get_start_method() == "spawn"
        self.max_workers = max_workers
        self.shut_down = False

    def submit(self, fn: Any, *args: Any, **kwargs: Any) -> Future[Any]:  # noqa: ANN401
        future: Future[Any] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # handed to the caller, as a pool does
            future.set_exception(exc)
        return future

    def shutdown(self, wait: bool, cancel_futures: bool) -> None:
        self.shut_down = True


def _points() -> list[Any]:
    single = _singles("mse")["individual"]
    return [single.with_parameter("budget_loading", v) for v in (1.0, 1.1, 1.2)]


def test_reference_runs_serial(monkeypatch: pytest.MonkeyPatch) -> None:
    a, b, c = _points()
    ran: list[str] = []

    def fake_run_single(single: Any, data: Any, store: Any, **kwargs: Any) -> None:  # noqa: ANN401
        assert kwargs == {"source": rdp.REFERENCE_SOURCE, "policy": rdp.DEFAULT_POLICY}
        ran.append(_run_id(single))

    monkeypatch.setattr(rdp, "run_single", fake_run_single)
    store: Any = _Store({_run_id(c)})
    with rdp.ReferenceRuns(DATA, store) as runs:
        runs.submit([a, b, a])
        runs.submit([c, b])
        assert ran == [_run_id(a), _run_id(b)]  # at once, each run once
        runs.wait()
    assert (runs.executed, runs.cached) == (2, 1)


def test_reference_runs_on_workers_write_in_submission_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b, c = _points()
    pools: list[_Executor] = []

    def executor(**kwargs: Any) -> _Executor:  # noqa: ANN401
        pools.append(_Executor(**kwargs))
        return pools[-1]

    def fake_execute(single: Any, data: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        assert kwargs == {"source": rdp.REFERENCE_SOURCE, "policy": rdp.DEFAULT_POLICY}
        run_id = _run_id(single)
        return SimpleNamespace(run_id=run_id), {"run_id": run_id}

    monkeypatch.setattr(rdp, "ProcessPoolExecutor", executor)
    monkeypatch.setattr(rdp, "execute", fake_execute)
    monkeypatch.setattr(rdp, "run_single", None)  # never on the parallel path
    store: Any = _Store({_run_id(b)})
    with rdp.ReferenceRuns(DATA, store, jobs=3) as runs:
        runs.submit([c, b, a, c])
        assert store.written == []  # the parent writes in wait()
        runs.wait()
    assert pools[0].max_workers == 3
    assert pools[0].shut_down
    assert store.written == [_run_id(c), _run_id(a)]
    assert (runs.executed, runs.cached) == (2, 1)


def test_reference_runs_raise_on_a_failed_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b, c = _points()
    monkeypatch.setattr(rdp, "ProcessPoolExecutor", _Executor)

    def returns(run_id: str | None = None, error: BaseException | None = None) -> Any:  # noqa: ANN401
        def fake_execute(single: Any, data: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            if error is not None and single is b:
                raise error
            rid = run_id or _run_id(single)
            return SimpleNamespace(run_id=rid), {"run_id": rid}

        return fake_execute

    # (execute, error raised by wait, its message, the runs written before it)
    cases: list[tuple[Any, type[Exception], str, list[str]]] = [
        (returns(run_id="another"), RuntimeError, "returned run another", []),
        (returns(error=BrokenProcessPool()), RuntimeError, "died", [_run_id(a)]),
        (returns(error=ValueError("bad config")), ValueError, "bad", [_run_id(a)]),
    ]
    for fake, error, match, written in cases:
        monkeypatch.setattr(rdp, "execute", fake)
        store: Any = _Store()
        with rdp.ReferenceRuns(DATA, store, jobs=2) as runs:
            runs.submit([a, b, c])
            with pytest.raises(error, match=match):
                runs.wait()
        assert store.written == written


def test_reference_runs_need_their_pool() -> None:
    store: Any = _Store()
    with pytest.raises(ValueError, match="at least 1"):
        rdp.ReferenceRuns(DATA, store, jobs=0)
    runs = rdp.ReferenceRuns(DATA, store, jobs=2)
    with pytest.raises(RuntimeError, match="outside its with block"):
        runs.submit(_points()[:1])


# -- real worker processes ---------------------------------------------------


@pytest.mark.parity_full
def test_reference_runs_on_workers_equal_the_serial_runs(tmp_path: Path) -> None:
    data = load_input(CONFIG)
    points = [
        s.with_parameter("budget_loading", v)
        for s in _singles("mse").values()
        for v in (1.0, 1.0005)
    ]
    parallel = ResultStore(tmp_path / "parallel")
    serial = ResultStore(tmp_path / "serial")
    with rdp.ReferenceRuns(data, parallel, jobs=2) as runs:
        runs.submit(points)
        runs.wait()
    assert (runs.executed, runs.cached) == (len(points), 0)
    for point in points:
        run_single(
            point, data, serial, source=rdp.REFERENCE_SOURCE, policy=rdp.DEFAULT_POLICY
        )
    run_ids = [_run_id(p) for p in points]
    timing = ["build_seconds", "solve_seconds", "created_at"]
    for table in ("runs", "payouts", "kpis"):
        frames = [
            pd.concat([store.read(table, run_ids=[r]) for r in run_ids])
            .drop(columns=timing, errors="ignore")
            .reset_index(drop=True)
            for store in (parallel, serial)
        ]
        pd.testing.assert_frame_equal(frames[0], frames[1])
