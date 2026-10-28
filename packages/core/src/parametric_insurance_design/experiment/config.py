"""Experiment configuration schema (SPEC §4.2, thesis issues C2, C4, C8).

Owner: MAR-63. Typed, validated configuration of one experiment: the EventSet,
the portfolio subset, the noise layer, the threshold filter, the outcome
basis, the sample, the payout structure, the scopes, the objectives, the
pricing, the extra constraints, the evaluation, the one-factor-at-a-time
sweeps and the output location. It replaces the thesis' four YAML files and
the notebook globals (``parity/configs/thesis.yaml`` is the migrated thesis
configuration, written by ``parity/scripts/migrate_thesis_config.py``).

Every model forbids unknown keys, and numbers are strict: booleans and
strings are not numbers, floats must be finite, and integer fields take
integers only (an integer is accepted for a float field). :func:`parse_config`
and :func:`load_config` turn every validation failure into one
:class:`~parametric_insurance_design.errors.ConfigError` that lists each
problem with its location in the file, e.g.
``noise.reshuffel: unknown key 'reshuffel' (allowed: ...)``. Component
parameters are checked by building the component at load time, so the
component's own checks (e.g. the last-bin width of
:class:`~parametric_insurance_design.payout.StepPayout`) also fail at load time.

Pipeline order (what the runner, MAR-64, does with a config; thesis order):

1. read the EventSet at ``eventset.path`` (and check ``eventset.checksum``);
2. keep the locations in ``portfolio.location_ids``;
3. apply ``noise`` (:func:`~parametric_insurance_design.noise.add_noise` with
   :meth:`NoiseConfig.rng`);
4. apply ``threshold`` (:meth:`EventSet.filter_threshold`);
5. split into samples (``sample``), then for each scope and objective build,
   solve and evaluate with the components of :meth:`ExperimentConfig.to_components`.

**Config hash.** :func:`config_hash` is the cache key of a run and the
``runs.config_hash`` column. See its docstring for the canonical form and the
fields it leaves out.

Examples
--------
>>> config = load_config("parity/configs/thesis.yaml")  # doctest: +SKIP
>>> components = config.to_components()  # doctest: +SKIP
>>> config_hash(config)  # doctest: +SKIP
'sha256:...'
"""

from __future__ import annotations

import difflib
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Self, get_args

import numpy as np
import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_serializer,
    model_validator,
)

from parametric_insurance_design.basis import Basis
from parametric_insurance_design.bootstrap import DEFAULT_LEVEL, DEFAULT_N_BOOTSTRAP
from parametric_insurance_design.clustering import ThesisWardClustering
from parametric_insurance_design.constraints import Budget
from parametric_insurance_design.errors import ComponentConfigError, ConfigError
from parametric_insurance_design.index import (
    EntityIndex,
    PointIndex,
    ValueWeightedIndex,
)
from parametric_insurance_design.interfaces import (
    Constraint,
    Objective,
    PayoutStructure,
    Pricing,
    Scope,
)
from parametric_insurance_design.noise import NoiseKind
from parametric_insurance_design.objectives import MSE, ExpectedUncovered, WeightedCVaR
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import CostOfCapitalLoad, PurePremium
from parametric_insurance_design.scopes import Cluster, Individual, Portfolio

__all__ = [
    "CONFIG_HASH_DOMAIN",
    "CONFIG_HASH_EXCLUDED",
    "OMITTED_WHEN_ABSENT",
    "SCHEMA_VERSION",
    "SWEEP_PARAMETERS",
    "BootstrapConfig",
    "BudgetConfig",
    "ClusterScopeConfig",
    "Components",
    "CostOfCapitalConfig",
    "EvaluationConfig",
    "EventSetConfig",
    "ExpectedUncoveredConfig",
    "ExperimentConfig",
    "FullSampleConfig",
    "HoldoutSampleConfig",
    "IndividualScopeConfig",
    "KFoldSampleConfig",
    "MSEConfig",
    "NoiseConfig",
    "OutputConfig",
    "PortfolioConfig",
    "PortfolioScopeConfig",
    "PurePremiumConfig",
    "StepPayoutConfig",
    "SweepConfig",
    "SweepParameter",
    "ThesisWardConfig",
    "ThresholdConfig",
    "WeightedCVaRConfig",
    "canonical_json",
    "config_hash",
    "dump_config",
    "load_config",
    "parse_config",
    "to_dict",
]

SCHEMA_VERSION: Final[int] = 1
"""Version of the configuration schema (``schema_version`` in every file)."""

CONFIG_HASH_DOMAIN: Final[str] = "parametric-insurance-design/config-hash/v1"
"""Domain tag that starts the hash input. Changing the canonical form bumps it."""

CONFIG_HASH_EXCLUDED: Final[Mapping[str, Any]] = {
    "name": True,
    "description": True,
    "eventset": {"path": True},
    "output": True,
    "sweeps": True,
}
"""Fields :func:`config_hash` leaves out (a pydantic ``exclude`` spec).

``name`` and ``description`` are labels. ``eventset.path`` and ``output`` are
locations: the data is identified by its content (``eventset.checksum``, and
the runner records ``EventSet.content_hash()``), and where results are written
does not change them. ``sweeps`` lists the variants to derive from the run:
each sweep point is a config of its own (:meth:`ExperimentConfig.with_parameter`)
with its own hash, so a sweep point equal to the baseline shares its cache
entry.
"""

SweepParameter = Literal[
    "alpha",
    "beta",
    "budget_loading",
    "n_bins",
    "n_clusters",
    "noise_level",
    "n_assets",
]
"""Parameters a one-factor-at-a-time sweep can vary.

``alpha`` and ``beta`` set every ``weighted_cvar`` objective, ``budget_loading``
every ``budget`` constraint, ``n_bins`` the step payout, ``n_clusters`` every
``cluster`` scope, ``noise_level`` the noise level (EventSet-rebuilding), and
``n_assets`` the size of the location subsets (EventSet-rebuilding; the
subsets are chosen by the sweep, MAR-65). The thesis name of ``noise_level``
is ``noise_value``.
"""

SWEEP_PARAMETERS: Final[tuple[str, ...]] = get_args(SweepParameter)
"""The values of :data:`SweepParameter`, in order."""

_INT_PARAMETERS: Final[frozenset[str]] = frozenset({"n_bins", "n_clusters", "n_assets"})
"""Sweep parameters with integer values; the others take floats."""

# --------------------------------------------------------------------------
# Field types
# --------------------------------------------------------------------------

StrictFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]
"""A finite float; integers are accepted, booleans and strings are not."""
StrictInt = Annotated[int, Field(strict=True)]
"""An integer; booleans, floats and strings are not."""
UnitOpen = Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0.0, lt=1.0)]
"""A finite float in ``(0, 1)``."""
UnitClosed = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0.0, le=1.0)]
"""A finite float in ``[0, 1]``."""
NonNegativeFloat = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0.0)]
"""A finite float >= 0."""
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
"""An integer >= 1."""
Seed = Annotated[int, Field(strict=True, ge=0)]
"""A seed for :func:`numpy.random.default_rng`, an integer >= 0."""
NonEmptyStr = Annotated[str, Field(strict=True, min_length=1)]
"""A non-empty string."""
IndexKind = Literal["point", "value_weighted"]
"""Entity index: ``PointIndex`` or ``ValueWeightedIndex``."""


class _Model(BaseModel):
    """Base of every config model: frozen, strict about unknown keys."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
    )

    @model_validator(mode="before")
    @classmethod
    def _reject_unknown_keys(cls, data: Any) -> Any:  # noqa: ANN401 (pydantic hook)
        """Reject unknown keys with the allowed keys and a close match."""
        if isinstance(data, Mapping):
            allowed = list(cls.model_fields)
            unknown = [str(k) for k in data if k not in cls.model_fields]
            if unknown:
                raise ValueError("; ".join(_unknown_key(k, allowed) for k in unknown))
        return data


def _unknown_key(key: str, allowed: Sequence[str]) -> str:
    """Message for one unknown key."""
    message = f"unknown key {key!r} (allowed: {', '.join(allowed)})"
    close = difflib.get_close_matches(key, allowed, n=1)
    if close:
        message += f"; did you mean {close[0]!r}?"
    return message


def _built(build: Any) -> None:  # noqa: ANN401 (any zero-argument callable)
    """Call a component constructor; turn its error into a validation error."""
    try:
        build()
    except ComponentConfigError as exc:
        raise ValueError(str(exc)) from exc


# --------------------------------------------------------------------------
# Data: EventSet, portfolio, noise, threshold
# --------------------------------------------------------------------------


class EventSetConfig(_Model):
    """Where the EventSet is, and optionally which content it must have.

    Parameters
    ----------
    path : pathlib.Path
        EventSet directory (``EventSet.from_parquet``). A relative path is
        relative to the config file's directory when the config is read with
        :func:`load_config`. Not part of the config hash.
    checksum : str or None, default None
        Expected ``EventSet.content_hash()`` (``"sha256:"`` and 64 hex
        digits). The runner checks it when it is set. Part of the config hash.
    """

    path: Path
    checksum: (
        Annotated[str, Field(strict=True, pattern=r"^sha256:[0-9a-f]{64}$")] | None
    ) = None


class PortfolioConfig(_Model):
    """Which locations of the EventSet form the portfolio.

    Parameters
    ----------
    location_ids : tuple of str or None, default None
        Locations to keep, in this order; unique. None keeps all, in EventSet
        order (thesis ``ASSETS``).
    """

    location_ids: tuple[NonEmptyStr, ...] | None = None

    @field_validator("location_ids")
    @classmethod
    def _unique(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        """Check that the subset is non-empty and has no repeats."""
        if value is None:
            return None
        if not value:
            raise ValueError("location_ids must not be empty (use null for all)")
        repeated = sorted({v for v in value if value.count(v) > 1})
        if repeated:
            raise ValueError(f"location_ids repeat {repeated}")
        return value


class NoiseConfig(_Model):
    """Thesis noise layer (:func:`~parametric_insurance_design.noise.add_noise`).

    Parameters
    ----------
    kind : {"homoscedastic", "heteroscedastic"}
        Noise model (thesis ``noise_type``).
    level : float
        Noise level ``eta >= 0`` (thesis ``noise_value``).
    n_copies : int
        Copies per event row, >= 1 (thesis ``reshuffel``).
    seed : int
        Seed of the generator, >= 0 (thesis ``RANDOM_SEED``).
    bounds : tuple of float, default (20.0, 70.0)
        Index range of the heteroscedastic ramp, ``low < high``. The thesis
        hard-coded its attachment and limit (issue C4).
    """

    kind: NoiseKind
    level: NonNegativeFloat
    n_copies: PositiveInt
    seed: Seed
    bounds: tuple[StrictFloat, StrictFloat] = (20.0, 70.0)

    @field_validator("bounds")
    @classmethod
    def _ordered(cls, value: tuple[float, float]) -> tuple[float, float]:
        """Check ``low < high``."""
        if not value[0] < value[1]:
            raise ValueError(f"bounds must satisfy low < high, got {list(value)}")
        return value

    def rng(self) -> np.random.Generator:
        """Return a fresh generator, ``numpy.random.default_rng(seed)``.

        Returns
        -------
        numpy.random.Generator
            A new generator on every call, so that every EventSet build draws
            the same numbers (thesis: one ``default_rng(RANDOM_SEED)`` per
            build).
        """
        return np.random.default_rng(self.seed)


class ThresholdConfig(_Model):
    """Threshold filter (:meth:`EventSet.filter_threshold`), for speed only.

    Parameters
    ----------
    value : float
        Keep rows whose ``column`` reaches ``value`` at some location. Thesis:
        the attachment (``Sub_Portfolio_Max_Wind >= ATTACHEMENT``).
    column : {"index", "loss"}, default "index"
        Matrix compared with the threshold.
    """

    value: StrictFloat
    column: Literal["index", "loss"] = "index"


# --------------------------------------------------------------------------
# Samples
# --------------------------------------------------------------------------


class FullSampleConfig(_Model):
    """Calibrate and evaluate on every row (in-sample, thesis)."""

    kind: Literal["full"]


class HoldoutSampleConfig(_Model):
    """Year-block holdout (:func:`~parametric_insurance_design.splits.holdout`).

    Parameters
    ----------
    train_fraction : float, default 0.7
        Share of years in the training block, in ``(0, 1)``.
    """

    kind: Literal["holdout"]
    train_fraction: UnitOpen = 0.7


class KFoldSampleConfig(_Model):
    """Year-block k-fold (:func:`~parametric_insurance_design.splits.year_block_kfold`).

    A k-fold experiment calibrates once per fold. Each fold is a run of its
    own (MAR-22): :meth:`ExperimentConfig.single_runs` expands a config
    without ``fold`` into one config per fold, so the fold is part of the
    :func:`config_hash` and of the ``run_id``, and the ``runs`` key
    ``(run_id, problem_id)`` stays unique without a ``fold`` column.

    Parameters
    ----------
    k : int, default 5
        Number of folds, >= 2.
    fold : int or None, default None
        The fold this run calibrates on, in ``0 .. k - 1``. None (the
        experiment level) means every fold; the runner needs it set.
    """

    kind: Literal["kfold"]
    k: Annotated[int, Field(strict=True, ge=2)] = 5
    fold: Annotated[int, Field(strict=True, ge=0)] | None = None

    @model_validator(mode="after")
    def _fold_in_range(self) -> Self:
        """Check that the fold lies in ``0 .. k - 1``."""
        if self.fold is not None and self.fold >= self.k:
            raise ValueError(
                f"fold {self.fold} is not in 0 .. {self.k - 1} (k={self.k})"
            )
        return self


SampleConfig = Annotated[
    FullSampleConfig | HoldoutSampleConfig | KFoldSampleConfig,
    Field(discriminator="kind"),
]
"""How rows are split into calibration and evaluation samples."""


# --------------------------------------------------------------------------
# Components: payout, scopes, objectives, pricing, constraints
# --------------------------------------------------------------------------


class StepPayoutConfig(_Model):
    """Step payout (:class:`~parametric_insurance_design.payout.StepPayout`).

    Parameters
    ----------
    kind : {"step"}, default "step"
        Payout structure.
    attachment : float
        Lowest breakpoint (thesis ``ATTACHEMENT``).
    limit : float
        Highest breakpoint (thesis ``LIMIT``).
    n_bins : int
        Number of bins, >= 1.
    breakpoints : tuple of float or None, default None
        Explicit breakpoints (``n_bins + 1`` values from ``attachment`` to
        ``limit``); uniform if None.
    """

    kind: Literal["step"] = "step"
    attachment: StrictFloat
    limit: StrictFloat
    n_bins: PositiveInt
    breakpoints: tuple[StrictFloat, ...] | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        """Build the component, so that its checks run at load time."""
        _built(self.build)
        return self

    def build(self) -> StepPayout:
        """Return the :class:`StepPayout`."""
        return StepPayout(
            attachment=self.attachment,
            limit=self.limit,
            n_bins=self.n_bins,
            breakpoints=self.breakpoints,
        )


def _entity_index(kind: IndexKind | None, default: type[EntityIndex]) -> EntityIndex:
    """Return the entity index of a scope; the scope's default when None."""
    if kind is None:
        return default()
    return PointIndex() if kind == "point" else ValueWeightedIndex()


class IndividualScopeConfig(_Model):
    """Individual scope (:class:`~parametric_insurance_design.scopes.Individual`).

    Parameters
    ----------
    index : {"point", "value_weighted"} or None, default None
        Entity index; None uses the scope's default (``point``).
    """

    kind: Literal["individual"]
    index: IndexKind | None = None

    def build(self) -> Individual:
        """Return the :class:`Individual` scope."""
        return Individual(index=_entity_index(self.index, PointIndex))


class PortfolioScopeConfig(_Model):
    """Portfolio scope (:class:`~parametric_insurance_design.scopes.Portfolio`).

    Parameters
    ----------
    index : {"point", "value_weighted"} or None, default None
        Entity index; None uses the scope's default (``point``).
    """

    kind: Literal["portfolio"]
    index: IndexKind | None = None

    def build(self) -> Portfolio:
        """Return the :class:`Portfolio` scope."""
        return Portfolio(index=_entity_index(self.index, PointIndex))


class ThesisWardConfig(_Model):
    """Thesis clustering (:class:`~.clustering.ThesisWardClustering`).

    Parameters
    ----------
    beta_tail : float
        Quantile level of the tail features, in ``(0, 1)`` (thesis
        ``TAIL_QUANTILE_LEVEL``).
    linkage : str, default "ward"
        Hierarchical linkage method.
    """

    kind: Literal["thesis_ward"]
    beta_tail: UnitOpen
    linkage: NonEmptyStr = "ward"

    @model_validator(mode="after")
    def _check(self) -> Self:
        """Build the component, so that its checks run at load time."""
        _built(self.build)
        return self

    def build(self) -> ThesisWardClustering:
        """Return the :class:`ThesisWardClustering` strategy."""
        return ThesisWardClustering(beta_tail=self.beta_tail, linkage=self.linkage)


class ClusterScopeConfig(_Model):
    """Cluster scope (:class:`~parametric_insurance_design.scopes.Cluster`).

    Parameters
    ----------
    n_clusters : int
        Number of clusters, >= 1 (thesis ``n_clusters``).
    strategy : ThesisWardConfig
        Clustering strategy.
    index : {"point", "value_weighted"} or None, default None
        Entity index; None uses the scope's default (``value_weighted``).
    cap_n_clusters : bool, default False
        In an ``n_assets`` sweep, give a location subset smaller than
        ``n_clusters`` the effective count ``min(n_clusters, n_locations)``
        (:meth:`effective_n_clusters`, MAR-131). The sweep writes it into the
        point's config, so the run's manifest, ``runs.parameters`` and its
        config hash carry the count the run used, and the sweep manifest
        records the requested and the effective count. False is the thesis
        behaviour: such a subset fails to build (``InputMismatchError``), as
        the thesis did. The scope itself never caps: a run whose own config
        asks for more clusters than it has locations fails.

    Notes
    -----
    ``cap_n_clusters`` is left out of :func:`to_dict`, :func:`dump_config`
    and :func:`canonical_json` when it is False, its default. A config that
    does not set it therefore dumps and hashes exactly as before MAR-131 (the
    parity config and its config hashes are unchanged); a config that sets
    it to True has a hash of its own.
    """

    kind: Literal["cluster"]
    n_clusters: PositiveInt
    strategy: ThesisWardConfig
    index: IndexKind | None = None
    cap_n_clusters: Annotated[bool, Field(strict=True)] = False

    @model_serializer(mode="wrap")
    def _drop_default_cap(self, handler: SerializerFunctionWrapHandler) -> Any:  # noqa: ANN401
        """Leave ``cap_n_clusters`` out of every dump while it is False."""
        data = handler(self)
        if not self.cap_n_clusters and isinstance(data, dict):
            data.pop("cap_n_clusters", None)
        return data

    def effective_n_clusters(self, n_locations: int) -> int:
        """Return the number of clusters a run on ``n_locations`` locations uses.

        Parameters
        ----------
        n_locations : int
            Number of locations of the run, >= 1.

        Returns
        -------
        int
            ``min(n_clusters, n_locations)`` with ``cap_n_clusters``,
            ``n_clusters`` without (the scope then refuses a count above
            ``n_locations``).

        Raises
        ------
        ConfigError
            If ``n_locations`` is not an integer >= 1.
        """
        if (
            isinstance(n_locations, bool)
            or not isinstance(n_locations, int | np.integer)
            or n_locations < 1
        ):
            raise ConfigError(
                f"n_locations must be an integer >= 1, got {n_locations!r}"
            )
        if self.cap_n_clusters:
            return min(self.n_clusters, int(n_locations))
        return self.n_clusters

    def build(self) -> Cluster:
        """Return the :class:`Cluster` scope."""
        return Cluster(
            strategy=self.strategy.build(),
            n_clusters=self.n_clusters,
            index=_entity_index(self.index, ValueWeightedIndex),
        )


ScopeConfig = Annotated[
    IndividualScopeConfig | PortfolioScopeConfig | ClusterScopeConfig,
    Field(discriminator="kind"),
]
"""One scope; ``kind`` is the scope's ``name``."""


class MSEConfig(_Model):
    """Mean squared basis risk (:class:`~parametric_insurance_design.objectives.MSE`).

    Thesis ``pure_basis_risk_minimization``.
    """

    kind: Literal["mse"]

    def build(self) -> MSE:
        """Return the :class:`MSE` objective."""
        return MSE()


class ExpectedUncoveredConfig(_Model):
    """Expected uncovered loss (:class:`~.objectives.ExpectedUncovered`).

    Thesis ``pure_uncovered_loss_minimization``.
    """

    kind: Literal["expected_uncovered"]

    def build(self) -> ExpectedUncovered:
        """Return the :class:`ExpectedUncovered` objective."""
        return ExpectedUncovered()


class WeightedCVaRConfig(_Model):
    """Weighted CVaR (:class:`~parametric_insurance_design.objectives.WeightedCVaR`).

    Thesis ``weighted_cvar_minimization``.

    Parameters
    ----------
    alpha : float
        Weight of the CVaR term, in ``[0, 1]``.
    beta : float
        CVaR confidence level, in ``(0, 1)``.
    """

    kind: Literal["weighted_cvar"]
    alpha: UnitClosed
    beta: UnitOpen

    def build(self) -> WeightedCVaR:
        """Return the :class:`WeightedCVaR` objective."""
        return WeightedCVaR(alpha=self.alpha, beta=self.beta)


ObjectiveConfig = Annotated[
    MSEConfig | ExpectedUncoveredConfig | WeightedCVaRConfig,
    Field(discriminator="kind"),
]
"""One objective; ``kind`` is the objective's ``name``."""


class PurePremiumConfig(_Model):
    """Pure premium ``E[pi]`` (:class:`~.pricing.PurePremium`)."""

    kind: Literal["pure"]

    def build(self) -> PurePremium:
        """Return the :class:`PurePremium` pricing."""
        return PurePremium()


class CostOfCapitalConfig(_Model):
    """Cost-of-capital load (:class:`~.pricing.CostOfCapitalLoad`).

    Parameters
    ----------
    rate : float
        Load ``r`` in ``[0, 1]``.
    q : float
        CVaR level of the payout tail, in ``(0, 1)``.
    """

    kind: Literal["cost_of_capital"]
    rate: UnitClosed
    q: UnitOpen

    def build(self) -> CostOfCapitalLoad:
        """Return the :class:`CostOfCapitalLoad` pricing (MAR-27)."""
        return CostOfCapitalLoad(rate=self.rate, q=self.q)


PricingConfig = Annotated[
    PurePremiumConfig | CostOfCapitalConfig,
    Field(discriminator="kind"),
]
"""The premium principle; ``kind`` is the pricing's ``name``."""


class BudgetConfig(_Model):
    """Premium budget (:class:`~parametric_insurance_design.constraints.Budget`).

    Parameters
    ----------
    loading : float
        ``kappa >= 0``: premium at most ``kappa * E[L]`` (thesis
        ``budget_loading``).
    """

    kind: Literal["budget"]
    loading: NonNegativeFloat

    def build(self) -> Budget:
        """Return the :class:`Budget` constraint."""
        return Budget(loading=self.loading)


ConstraintConfig = Annotated[BudgetConfig, Field(discriminator="kind")]
"""One extra constraint; ``kind`` is the constraint's ``name``."""


# --------------------------------------------------------------------------
# Evaluation, sweeps, output
# --------------------------------------------------------------------------


class EvaluationConfig(_Model):
    """KPI settings (:func:`~parametric_insurance_design.evaluate.kpis`).

    Parameters
    ----------
    beta : float
        VaR/CVaR level of the KPIs, in ``(0, 1)`` (thesis ``BENCHMARK_BETA``).
        Independent of the objectives' ``beta``: a ``beta`` sweep changes the
        objectives only, as in the thesis.
    """

    beta: UnitOpen


class BootstrapConfig(_Model):
    """Block-bootstrap confidence intervals of the KPIs (MAR-23, SPEC §6.1).

    The runner resamples the years of every evaluation sample
    (``bootstrap.resample_years``) and fills the ``ci_*`` columns of the
    ``kpis`` table (``bootstrap.bootstrap_kpis``). Point estimates do not
    change. Each sample gets a fresh generator from ``seed``, so runs with
    the same seed and the same evaluation sample draw the same years: their
    intervals are computed on the same resamples (paired).

    Parameters
    ----------
    seed : int
        Seed of :meth:`rng`, >= 0.
    n_bootstrap : int, default 1000
        Number of replicates ``B``, >= 1.
    level : float, default 0.9
        Confidence level of the intervals, in ``(0, 1)``.
    """

    seed: Seed
    n_bootstrap: PositiveInt = DEFAULT_N_BOOTSTRAP
    level: UnitOpen = DEFAULT_LEVEL

    def rng(self) -> np.random.Generator:
        """Return a fresh generator, ``numpy.random.default_rng(seed)``.

        Returns
        -------
        numpy.random.Generator
            A new generator on every call.
        """
        return np.random.default_rng(self.seed)


class SweepConfig(_Model):
    """One one-factor-at-a-time sweep.

    Parameters
    ----------
    parameter : SweepParameter
        The parameter varied (:data:`SweepParameter`).
    values : tuple of float or int
        Values, non-empty and unique. Each must give a valid config.
    max_combinations : int or None, default None
        ``n_assets`` only: at most this many location subsets per size,
        sampled with ``seed`` (thesis ``max_combos_per_n``). None takes all.
    seed : int or None, default None
        ``n_assets`` only: seed of the subset sampling; required with
        ``max_combinations``.
    """

    parameter: SweepParameter
    values: tuple[StrictInt | StrictFloat, ...]
    max_combinations: PositiveInt | None = None
    seed: Seed | None = None

    @field_validator("values")
    @classmethod
    def _kinds(
        cls, value: tuple[int | float, ...], info: ValidationInfo
    ) -> tuple[int | float, ...]:
        """Floats for float parameters (``0`` becomes ``0.0``); integers otherwise."""
        parameter = info.data.get("parameter")
        if parameter in _INT_PARAMETERS:
            floats = [v for v in value if isinstance(v, float)]
            if floats:
                raise ValueError(f"{parameter} values must be integers, got {floats}")
            return value
        return tuple(float(v) for v in value)

    @model_validator(mode="after")
    def _check(self) -> Self:
        """Check the values and the ``n_assets``-only fields."""
        if not self.values:
            raise ValueError(f"sweep {self.parameter!r} has no values")
        repeated = sorted({v for v in self.values if self.values.count(v) > 1})
        if repeated:
            raise ValueError(f"sweep {self.parameter!r} repeats values {repeated}")
        if self.parameter != "n_assets":
            extra = [
                name
                for name in ("max_combinations", "seed")
                if getattr(self, name) is not None
            ]
            if extra:
                raise ValueError(f"{', '.join(extra)} only apply to n_assets sweeps")
        elif self.max_combinations is not None and self.seed is None:
            raise ValueError("an n_assets sweep with max_combinations needs a seed")
        return self


class OutputConfig(_Model):
    """Where results go. Not part of the config hash.

    Parameters
    ----------
    directory : pathlib.Path
        Result-store directory (MAR-64). A relative path is relative to the
        config file's directory when read with :func:`load_config`.
    """

    directory: Path


# --------------------------------------------------------------------------
# Experiment
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Components:
    """The component objects of a config (:meth:`ExperimentConfig.to_components`).

    Parameters
    ----------
    payout : PayoutStructure
        Shared by every design problem.
    scopes : tuple of Scope
        In config order.
    objectives : tuple of Objective
        In config order.
    pricing : Pricing
        Premium principle.
    constraints : tuple of Constraint
        Extra constraints, in config order.
    basis : Basis
        Outcome basis of objective, premium, budget and KPIs.
    """

    payout: PayoutStructure
    scopes: tuple[Scope, ...]
    objectives: tuple[Objective, ...]
    pricing: Pricing
    constraints: tuple[Constraint, ...]
    basis: Basis


class ExperimentConfig(_Model):
    """One experiment: data, components, evaluation, sweeps and output.

    A config describes the runs of every scope with every objective (thesis:
    3 x 3), plus the sweeps derived from them. :meth:`single_runs` splits it
    into one config per (scope, objective), each with its own
    :func:`config_hash`.

    Parameters
    ----------
    schema_version : int
        Must be :data:`SCHEMA_VERSION`.
    name : str
        Label of the experiment. Not part of the config hash.
    description : str, default ""
        Free text. Not part of the config hash.
    eventset : EventSetConfig
        Input EventSet.
    portfolio : PortfolioConfig, default all locations
        Location subset.
    noise : NoiseConfig or None, default None
        Noise layer; None for none.
    threshold : ThresholdConfig or None, default None
        Threshold filter, applied after the noise; None for none.
    basis : Basis
        ``event_conditional`` (thesis parity), ``event`` or ``annual``.
    sample : FullSampleConfig, HoldoutSampleConfig or KFoldSampleConfig
        Calibration and evaluation samples. Default ``full`` (in-sample).
    payout : StepPayoutConfig
        Payout structure.
    scopes : tuple of scope configs
        Non-empty, no repeats.
    objectives : tuple of objective configs
        Non-empty, no repeats.
    pricing : PurePremiumConfig or CostOfCapitalConfig, default pure
        Premium principle.
    constraints : tuple of BudgetConfig, default ()
        Extra constraints; no repeated kind.
    evaluation : EvaluationConfig
        KPI settings.
    bootstrap : BootstrapConfig or None, default None
        Confidence intervals of the KPIs; None for none (null ``ci_*``
        columns). Opt-in: when None it is left out of :func:`config_hash` and
        :func:`to_dict`, so configs without it keep their hashes.
    sweeps : tuple of SweepConfig, default ()
        One-factor-at-a-time sweeps; one per parameter, each applicable to
        this config.
    output : OutputConfig
        Result location.

    Raises
    ------
    pydantic.ValidationError
        From the constructor and ``model_validate`` if the config is invalid.
        :func:`parse_config` and :func:`load_config` raise
        :class:`~parametric_insurance_design.errors.ConfigError` instead.
    """

    schema_version: StrictInt
    name: NonEmptyStr
    description: Annotated[str, Field(strict=True)] = ""
    eventset: EventSetConfig
    portfolio: PortfolioConfig = PortfolioConfig()
    noise: NoiseConfig | None = None
    threshold: ThresholdConfig | None = None
    basis: Basis
    sample: SampleConfig = FullSampleConfig(kind="full")
    payout: StepPayoutConfig
    scopes: tuple[ScopeConfig, ...]
    objectives: tuple[ObjectiveConfig, ...]
    pricing: PricingConfig = PurePremiumConfig(kind="pure")
    constraints: tuple[ConstraintConfig, ...] = ()
    evaluation: EvaluationConfig
    bootstrap: BootstrapConfig | None = None
    sweeps: tuple[SweepConfig, ...] = ()
    output: OutputConfig

    @field_validator("schema_version")
    @classmethod
    def _version(cls, value: int) -> int:
        """Accept the current schema version only."""
        if value != SCHEMA_VERSION:
            raise ValueError(
                f"schema_version {value} is not supported (expected {SCHEMA_VERSION})"
            )
        return value

    @field_validator("scopes", "objectives")
    @classmethod
    def _non_empty_unique(cls, value: tuple[BaseModel, ...]) -> tuple[BaseModel, ...]:
        """At least one entry and no identical entries."""
        if not value:
            raise ValueError("must list at least one entry")
        _no_repeats(value, lambda m: m.model_dump_json())
        return value

    @field_validator("constraints")
    @classmethod
    def _one_per_kind(cls, value: tuple[BudgetConfig, ...]) -> tuple[BudgetConfig, ...]:
        """At most one constraint of each kind."""
        _no_repeats(value, lambda m: m.kind)
        return value

    @model_validator(mode="after")
    def _check(self) -> Self:
        """Check the sweeps against the rest of the config."""
        _no_repeats(self.sweeps, lambda s: s.parameter)
        for sweep in self.sweeps:
            if sweep.parameter == "n_assets":
                self._check_n_assets(sweep)
                continue
            for value in sweep.values:
                try:
                    self.with_parameter(sweep.parameter, value)
                except ConfigError as exc:
                    raise ValueError(
                        f"sweep {sweep.parameter!r}, value {value!r}: {exc}"
                    ) from exc
        return self

    def _check_n_assets(self, sweep: SweepConfig) -> None:
        """``n_assets`` values are integers within the portfolio size."""
        bad = [v for v in sweep.values if isinstance(v, float) or v < 1]
        if bad:
            raise ValueError(f"n_assets sweep values must be integers >= 1, got {bad}")
        ids = self.portfolio.location_ids
        if ids is not None and max(sweep.values) > len(ids):
            raise ValueError(
                f"n_assets sweep value {max(sweep.values)} exceeds the "
                f"{len(ids)} portfolio locations"
            )

    # -- components ----------------------------------------------------------

    def to_components(self) -> Components:
        """Build the component objects.

        Returns
        -------
        Components
            Payout structure, scopes, objectives, pricing, constraints and
            basis, ready for ``problem.build_problems``.
        """
        return Components(
            payout=self.payout.build(),
            scopes=tuple(s.build() for s in self.scopes),
            objectives=tuple(o.build() for o in self.objectives),
            pricing=self.pricing.build(),
            constraints=tuple(c.build() for c in self.constraints),
            basis=self.basis,
        )

    # -- derived configs -----------------------------------------------------

    def single_runs(self) -> tuple[ExperimentConfig, ...]:
        """Split into one config per (scope, objective), without sweeps.

        A k-fold sample without a ``fold`` is also split per fold, so each
        fold is a run of its own (:class:`KFoldSampleConfig`).

        Returns
        -------
        tuple of ExperimentConfig
            Scope-major (every objective for the first scope, then the next),
            in config order, and for k-fold fold-minor (folds ``0 .. k - 1``
            of a scope and objective next to each other). Each has one scope,
            one objective, no sweeps and, for k-fold, one fold; its
            :func:`config_hash` is the cache key of that run.
        """
        sample = self.sample
        samples: list[dict[str, Any]] = [sample.model_dump(mode="python")]
        if sample.kind == "kfold" and sample.fold is None:
            samples = [
                sample.model_copy(update={"fold": f}).model_dump(mode="python")
                for f in range(sample.k)
            ]
        return tuple(
            self._replaced(scopes=[scope], objectives=[objective], sweeps=[], sample=s)
            for scope in self.scopes
            for objective in self.objectives
            for s in samples
        )

    def applies(self, parameter: str) -> bool:
        """Whether a sweep parameter applies to this config.

        Parameters
        ----------
        parameter : str
            One of :data:`SWEEP_PARAMETERS`.

        Returns
        -------
        bool
            ``alpha``/``beta``: a ``weighted_cvar`` objective is listed;
            ``budget_loading``: a budget constraint is listed; ``n_bins``:
            the payout has no explicit breakpoints; ``n_clusters``: a
            ``cluster`` scope is listed; ``noise_level``: noise is set;
            ``n_assets``: always.

        Raises
        ------
        ConfigError
            If ``parameter`` is not a sweep parameter.
        """
        if parameter in ("alpha", "beta"):
            return any(o.kind == "weighted_cvar" for o in self.objectives)
        if parameter == "budget_loading":
            return any(c.kind == "budget" for c in self.constraints)
        if parameter == "n_bins":
            return self.payout.breakpoints is None
        if parameter == "n_clusters":
            return any(s.kind == "cluster" for s in self.scopes)
        if parameter == "noise_level":
            return self.noise is not None
        if parameter == "n_assets":
            return True
        raise ConfigError(
            f"unknown sweep parameter {parameter!r} "
            f"(allowed: {', '.join(SWEEP_PARAMETERS)})"
        )

    def with_parameter(self, parameter: str, value: float | int) -> ExperimentConfig:
        """Return the config of one sweep point.

        Parameters
        ----------
        parameter : str
            One of :data:`SWEEP_PARAMETERS` except ``n_assets`` (use
            :meth:`with_locations`).
        value : float or int
            New value. ``alpha`` and ``beta`` set every ``weighted_cvar``
            objective, ``budget_loading`` the budget, ``n_bins`` the payout,
            ``n_clusters`` every cluster scope, ``noise_level`` the noise.

        Returns
        -------
        ExperimentConfig
            A validated copy with the new value and no sweeps.

        Raises
        ------
        ConfigError
            If the parameter is unknown, is ``n_assets``, does not apply to
            this config (:meth:`applies`), or the value is invalid.
        """
        if parameter == "n_assets":
            raise ConfigError(
                "n_assets sweeps choose location subsets; use with_locations()"
            )
        if not self.applies(parameter):
            raise ConfigError(f"sweep parameter {parameter!r} does not apply here")
        data = self.model_dump(mode="python", round_trip=True)
        data["sweeps"] = []
        if parameter in ("alpha", "beta"):
            for objective in data["objectives"]:
                if objective["kind"] == "weighted_cvar":
                    objective[parameter] = value
        elif parameter == "budget_loading":
            for constraint in data["constraints"]:
                if constraint["kind"] == "budget":
                    constraint["loading"] = value
        elif parameter == "n_bins":
            data["payout"]["n_bins"] = value
        elif parameter == "n_clusters":
            for scope in data["scopes"]:
                if scope["kind"] == "cluster":
                    scope["n_clusters"] = value
        else:  # noise_level
            data["noise"]["level"] = value
        return _validate(data, source=f"{parameter}={value!r}")

    def with_locations(self, location_ids: Sequence[str]) -> ExperimentConfig:
        """Return the config of one location subset (``n_assets`` sweep point).

        Parameters
        ----------
        location_ids : sequence of str
            The subset, in order.

        Returns
        -------
        ExperimentConfig
            A validated copy with ``portfolio.location_ids`` replaced and no
            sweeps.

        Raises
        ------
        ConfigError
            If the subset is empty, repeats a location, or is not part of the
            configured portfolio.
        """
        ids = list(location_ids)
        current = self.portfolio.location_ids
        if current is not None:
            outside = [loc for loc in ids if loc not in current]
            if outside:
                raise ConfigError(f"locations not in the portfolio: {outside}")
        return self._replaced(portfolio={"location_ids": ids}, sweeps=[])

    def _replaced(self, **fields: Any) -> ExperimentConfig:  # noqa: ANN401
        """Return a validated copy with some top-level fields replaced."""
        data = self.model_dump(mode="python", round_trip=True)
        for key, value in fields.items():
            data[key] = [_dump(v) for v in value] if isinstance(value, list) else value
        return _validate(data, source="derived config")


def _dump(value: object) -> object:
    """Return a model as a dict, anything else unchanged."""
    return (
        value.model_dump(mode="python", round_trip=True)
        if isinstance(value, BaseModel)
        else value
    )


def _no_repeats(items: Sequence[Any], key: Any) -> None:  # noqa: ANN401
    """Raise ``ValueError`` if two items have the same key."""
    seen: set[Any] = set()
    repeated: list[Any] = []
    for item in items:
        k = key(item)
        if k in seen and k not in repeated:
            repeated.append(k)
        seen.add(k)
    if repeated:
        raise ValueError(f"repeated entries: {repeated}")


# --------------------------------------------------------------------------
# Reading, writing, hashing
# --------------------------------------------------------------------------


def _format_errors(error: ValidationError, source: str | None) -> str:
    """One line per validation error: location, message, offending input."""
    lines: list[str] = []
    for item in error.errors(include_url=False):
        loc = "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}" for part in item["loc"]
        ).lstrip(".")
        message = str(item["msg"]).removeprefix("Value error, ")
        line = f"  {loc or '<root>'}: {message}"
        given = item.get("input")
        if item["type"] not in ("value_error", "missing") and not isinstance(
            given, Mapping
        ):
            text = repr(given)
            line += f" (got {text if len(text) <= 60 else text[:57] + '...'})"
        lines.append(line)
    where = f" ({source})" if source else ""
    count = len(lines)
    plural = "s" if count != 1 else ""
    return f"invalid config{where}, {count} problem{plural}:\n" + "\n".join(lines)


def _validate(data: object, *, source: str | None) -> ExperimentConfig:
    """``model_validate`` with errors as :class:`ConfigError`."""
    try:
        return ExperimentConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_errors(exc, source)) from exc


def parse_config(
    data: Mapping[str, Any],
    *,
    base_dir: str | Path | None = None,
    source: str | None = None,
) -> ExperimentConfig:
    """Validate a config mapping (e.g. parsed YAML).

    Parameters
    ----------
    data : mapping
        The config.
    base_dir : str or pathlib.Path, optional
        Directory that relative ``eventset.path`` and ``output.directory`` are
        resolved against. If None, relative paths stay relative.
    source : str, optional
        Name of the source (e.g. a file path) for error messages.

    Returns
    -------
    ExperimentConfig
        The validated config.

    Raises
    ------
    ConfigError
        If ``data`` is not a mapping, or the config is invalid. The message
        lists every problem with its location.
    """
    if not isinstance(data, Mapping):
        where = f" ({source})" if source else ""
        raise ConfigError(
            f"invalid config{where}: expected a mapping, got {type(data).__name__}"
        )
    config = _validate(data, source=source)
    if base_dir is None:
        return config
    base = Path(base_dir)
    eventset = config.eventset.model_copy(
        update={"path": _resolve(base, config.eventset.path)}
    )
    output = config.output.model_copy(
        update={"directory": _resolve(base, config.output.directory)}
    )
    return config.model_copy(update={"eventset": eventset, "output": output})


def _resolve(base: Path, path: Path) -> Path:
    """``path`` if absolute, else ``base / path``, normalised."""
    return path if path.is_absolute() else (base / path).resolve()


def load_config(path: str | Path) -> ExperimentConfig:
    """Read a YAML config file.

    Relative paths in the file (``eventset.path``, ``output.directory``) are
    resolved against the file's directory, so the result does not depend on
    the working directory.

    Parameters
    ----------
    path : str or pathlib.Path
        YAML file.

    Returns
    -------
    ExperimentConfig
        The validated config, with absolute paths.

    Raises
    ------
    ConfigError
        If the file cannot be read, is not valid YAML, or the config is
        invalid.
    """
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config {file}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"config {file} is not valid YAML: {exc}") from exc
    return parse_config(data, base_dir=file.resolve().parent, source=str(file))


def to_dict(config: ExperimentConfig) -> dict[str, Any]:
    """Return the config as plain JSON/YAML types (str, int, float, list, dict).

    Every field is written, defaults included, so the output is complete.
    Paths are written as POSIX strings.
    """
    data = _drop_absent(config.model_dump(mode="json", round_trip=True))
    data["eventset"]["path"] = config.eventset.path.as_posix()
    data["output"]["directory"] = config.output.directory.as_posix()
    return data


def dump_config(config: ExperimentConfig) -> str:
    """Return the config as YAML that :func:`load_config` reads back.

    Parameters
    ----------
    config : ExperimentConfig
        The config.

    Returns
    -------
    str
        YAML, keys in schema order, every field written.
    """
    return yaml.dump(
        to_dict(config),
        Dumper=_ConfigDumper,
        sort_keys=False,
        allow_unicode=False,
        width=88,
    )


class _ConfigDumper(yaml.SafeDumper):
    """Block-style mappings; lists of scalars on one line (``[1, 2, 3]``)."""


def _represent_list(dumper: yaml.SafeDumper, data: list[Any]) -> yaml.Node:
    """Write a list of scalars in flow style, other lists in block style."""
    flow = all(not isinstance(item, dict | list) for item in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)


_ConfigDumper.add_representer(list, _represent_list)


OMITTED_WHEN_ABSENT: Final[tuple[str, ...]] = ("bootstrap",)
"""Optional top-level sections left out of :func:`canonical_json` and
:func:`to_dict` when they are None.

They were added after configs were hashed and cached (``bootstrap``: MAR-23).
Leaving an absent section out keeps the hash, and the YAML, of every config
without it exactly as before; a config that sets it hashes the section.
"""


def _drop_absent(data: dict[str, Any]) -> dict[str, Any]:
    """Remove the :data:`OMITTED_WHEN_ABSENT` keys whose value is None."""
    return {
        k: v for k, v in data.items() if not (k in OMITTED_WHEN_ABSENT and v is None)
    }


def _normalise(value: Any) -> Any:  # noqa: ANN401 (JSON tree)
    """Write ``-0.0`` as ``0.0`` throughout a JSON tree.

    Non-finite floats cannot occur (the schema rejects them), and
    ``json.dumps(..., allow_nan=False)`` would refuse them.
    """
    if isinstance(value, dict):
        return {k: _normalise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalise(v) for v in value]
    if isinstance(value, float) and value == 0.0:
        return 0.0
    return value


def canonical_json(config: ExperimentConfig) -> str:
    """Return the canonical JSON that :func:`config_hash` hashes.

    Parameters
    ----------
    config : ExperimentConfig
        The config.

    Returns
    -------
    str
        The config without :data:`CONFIG_HASH_EXCLUDED` and without the
        absent :data:`OMITTED_WHEN_ABSENT` sections, every remaining field
        included (defaults too), as JSON with sorted keys, no
        whitespace (``(",", ":")`` separators) and ASCII escapes. Floats are
        written with Python's ``repr`` (the shortest string that round-trips,
        e.g. ``0.1``, ``1.0``, ``1e-05``) and ``-0.0`` as ``0.0``; integers
        without a decimal point. Float fields hold floats after validation,
        so ``1`` and ``1.0`` in a file give the same JSON. List order is
        content (scopes, objectives and constraints run in that order).
    """
    payload = _drop_absent(
        config.model_dump(mode="json", exclude=dict(CONFIG_HASH_EXCLUDED))
    )
    return json.dumps(
        _normalise(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def config_hash(config: ExperimentConfig) -> str:
    """Return the SHA-256 hash of a config, the cache key of a run.

    Parameters
    ----------
    config : ExperimentConfig
        The config, typically one of :meth:`ExperimentConfig.single_runs`.

    Returns
    -------
    str
        ``"sha256:"`` and 64 lowercase hex digits (the format of
        ``EventSet.content_hash()``), over the UTF-8 bytes of
        :data:`CONFIG_HASH_DOMAIN`, a NUL byte and :func:`canonical_json`.

    Notes
    -----
    Left out (:data:`CONFIG_HASH_EXCLUDED`): ``name``, ``description``,
    ``eventset.path``, ``output`` and ``sweeps``. Two configs that differ only
    there have the same hash. An absent ``bootstrap`` section (None) is also
    left out (:data:`OMITTED_WHEN_ABSENT`), so the opt-in bootstrap did not
    change the hash of any existing config. A set ``bootstrap`` section is
    hashed: the confidence intervals are part of the run's stored ``kpis``
    table, so a run with other (or no) intervals is another cache entry.
    ``eventset.checksum`` is included, so a run pinned to a checksum has a
    hash that names its data. A config without a checksum does not identify
    its data: the runner keys its cache on the pair (config hash,
    ``EventSet.content_hash()``).

    Any change to the canonical form or the exclusions changes
    :data:`CONFIG_HASH_DOMAIN`. (Omitting an absent ``bootstrap`` did not:
    the canonical JSON of every config that existed before it is unchanged.)
    Adding a schema field with a default changes
    the hash of every config, because defaults are hashed; that is a schema
    version change.
    """
    data = (
        CONFIG_HASH_DOMAIN.encode("utf-8")
        + b"\0"
        + canonical_json(config).encode("ascii")
    )
    return f"sha256:{hashlib.sha256(data).hexdigest()}"
