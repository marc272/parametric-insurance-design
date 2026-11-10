# CLIMADA design facts (K-12)

Measured facts about CLIMADA that the module design rests on (issue MAR-311, for ADR 0006, MAR-48). This page holds **observations, not conclusions**. Interpretation and recommendations go into the ADR, for the owner's decision.

Questions 1 to 8 are answered in order below. Every number comes with its setup and the command that produced it. The scripts are in `packages/climada/scripts/k12_*.py`. Their JSON output and the downloaded data are not committed.

## Environments

| Label | CLIMADA | Petals | Python | scipy | numpy | pandas | cvxpy | highspy | Source |
|---|---|---|---|---|---|---|---|---|---|
| `6.1-lock` | 6.1.0 (`pyhd8ed1ab_4`) | none | 3.12.15 | 1.15.2 | 2.3.5 | 2.3.3 | 1.9.3 | 1.15.1 | the repository's `packages/climada/pixi.lock` |
| `6.2.0` | 6.2.0 (`pypyhd8ed1ab_0`) | none | 3.11.18 | 1.17.1 | 2.4.6 | 2.2.3 | 1.9.3 | 1.15.1 | throwaway pixi manifest, conda-forge |
| `dev` | develop `a3d101a` (`6.2.1-dev`, 2026-11-06) | develop `3f57dcf` (`6.2.1-dev`, 2026-10-02) | 3.12.16 | 1.18.1 | 2.5.4 | 2.2.3 | 1.9.3 | 1.15.1 | throwaway pixi manifest: the two `requirements/env_climada.yml` at those commits, plus both packages from source tarballs |
| `pypi-X` | none | none | 3.12.11 | X | see Q5 | see Q5 | none | none | one uv venv per scipy version, wheels from PyPI |

Machine for all runs: Apple M4, 10 cores, 16 GB, macOS 15 (Darwin 24.6), osx-arm64, shared with other work, so treat the timings as orders of magnitude. All of this was installed under the git-ignored `results/` and removed afterwards. No lockfile or manifest of the repository was changed. Run on 2026-11-08.

The source of `climada/` at develop `a3d101a` differs from tag `v6.2.0` (`cc0b215`) only in `_version.py`. `climada_petals/engine/cat_bonds/` at develop `3f57dcf` is identical to tag `v6.2.0` (`6ecd7af`).

## Q1. Environment

**Is climada 6.2.0 on conda-forge?** Yes. Build `pypyhd8ed1ab_0`, uploaded 2026-11-06 16:00 UTC (`pixi search -c conda-forge climada`). PyPI has it too (2026-11-06 13:00 UTC, `requires-python >=3.11,<3.14`).

Things that differ from what a move to 6.2.0 might assume:

- The conda-forge build depends on both `python >=3.11,<3.14` and `python 3.11.*`. A solve with `python = "3.12.*"` fails with a message that names `python 3.11.*`, and one with `python = "3.11.*"` succeeds. The repository's lock uses Python 3.12. The PyPI metadata has no such limit.
- `climada-petals` on conda-forge is still 6.2.0 (2026-06-16) and pins `climada 6.1.*`. A solve with `climada ==6.2.0` and `climada-petals` fails (checked on `osx-arm64`; both packages are noarch), because no petals build accepts it. Petals `develop` declares `climada>=6.1`, Python `>=3.11,<3.14` and `pymoo` as mandatory.
- CLIMADA 6.2.0 pins `scipy 1.17.*`, against `1.15.*` for 6.1.0. Its dependency list has neither cvxpy nor highspy. In `6.2.0`, `pixi tree --invert` shows that `highspy` comes from `cvxpy`, and `cvxpy` from this repository's core.

**Does the prototype pass its tests?**

| Environment | Suite | Result | Command |
|---|---|---|---|
| `6.1-lock` (baseline) | `packages/climada` (`tests/` and `src/petals_parametric/test/`) | 743 passed, 1 skipped | `pixi run --locked test` |
| `6.2.0` | same | 736 passed, 1 failed, 6 errors, 1 skipped | `pytest`, plain |
| `6.2.0` | same | 743 passed, 1 skipped | `pytest` with `DYLD_FALLBACK_LIBRARY_PATH=$ENV/lib` |
| `dev` | same | 743 passed, 1 skipped | `pytest` with the same variable |
| `6.2.0`, `dev` | prototype only: `src/petals_parametric/test` and `tests/test_petals_parametric_{parity,isolation,readme}.py` | 301 passed each | same |

The one skipped test needs the IRIS catalogue, absent in all three environments. All tests ran with a pytest plugin that refuses Python-level network connections.

**What breaks?** No test of the prototype or the adapter fails once the library path below is set. The only failures on `6.2.0` were `ImportError: Missing optional dependency 'pytables'` in `tests/test_portfolio_litpop.py` and `tests/test_hazard_years.py`. The cause is outside CLIMADA: on `osx-arm64`, `c-blosc2 3.5.0 h7c780c3_0` links `liblz4` by the absolute path `/opt/homebrew/opt/lz4/lib/liblz4.1.dylib` (`otool -L`), which does not exist here. `linux-64` was not tested.

- `Exposures.gdf`, named in the issue as deprecated, is a plain property in 6.2.0 and `develop`, with no deprecation decorator. It is not under "Deprecated" in the 6.2.0 changelog. The `6.2.0` test log has no deprecation warning about it, and the `dev` log's warnings do not mention it.
- The 6.2.0 changelog's "Deprecated" entry is `Impact.calc_freq_curve(return_per=...)`. The prototype does not call it. "Removed" lists `climada.util.earth_engine` and two `climada.util.finance` constants; the prototype uses none of them. `develop` adds two cartopy `DeprecationWarning`s on import.

Noticed in passing, on 6.1.0 and 6.2.0 alike: if a `Centroids` object holds the same coordinates twice, `TropCyclone.from_tracks` returns an intensity matrix with one column fewer than the centroids and a column index of −1, and `check_matrices` then raises `indices must be >= 0`. Two insured points at the same location would meet this if the centroids are built from the exposures.

## Q2. Event and year structure of the Data API hazards

**Setup.** `climada.util.api_client.Client` against the public Data API, no credentials, CLIMADA 6.2.0, with `local_data.system` pointed at a git-ignored folder through a `climada.conf`. The script checks each dataset's size before downloading. None was above the 2 GB limit, so none was skipped. Total 387 MB, deleted afterwards. Country: Jamaica (`JAM`) for all hazards, except `storm_europe`, which has no dataset for Jamaica (0 listed) and uses Luxembourg (`LUX`).

```
python packages/climada/scripts/k12_data_api_facts.py --out facts.json
```

| Label | Dataset, version, size | Events | With intensity in the country |
|---|---|---|---|
| RW present | `tropical_cyclone_10synth_tracks_150arcsec_JAM_1980_2020` v2.1, 6.20 MB | 43,560 | 160 |
| RW rcp45 2060 | `tropical_cyclone_10synth_tracks_150arcsec_rcp45_JAM_2060` v2.1, 6.20 MB | 43,560 | 160 |
| RW rcp85 2060 | `tropical_cyclone_10synth_tracks_150arcsec_rcp85_JAM_2060` v2.1, 5.43 MB | 42,790 | 160 |
| TC observed | `tropical_cyclone_0synth_tracks_150arcsec_historical_JAM_1980_2020` v2, 0.48 MB | 3,890 | 13 |
| STORM present | `TC_JAM_0300as_STORM` v1.1, 164 MB | 712,800 | 4,233 |
| STORM rcp85 | `TC_JAM_0300as_STORM_CMCC-CM2-VHR4` v1.1, 186 MB | 694,333 | 5,032 |
| Flood hist | `river_flood_150arcsec_hist_JAM_1980_2000` v2, 0.19 MB | 920 | 920 |
| Flood rcp60 | `river_flood_150arcsec_rcp60_JAM_2050_2070` v3, 0.13 MB | 480 | 480 |
| Earthquake | `earthquake_hist_above4_388` v1.1, 3.58 MB | 41,710 | 16 |
| Wildfire | `wildfire_JAM_150arcsec_historical_2001_2020` v1.1, 0.07 MB | 20 | 20 |
| Windstorm | `storm_europe_150arcsec_LUX` v1.2, 14.1 MB | 4,260 | 4,260 |

Every dataset has licence CC BY 4.0 and `frequency_unit` `1/year`. The tropical-cyclone country files hold every storm of the global set, so most events have no wind in the country.

The issue names STORM at rcp45 and 2060. STORM's future datasets are rcp85 with one per GCM and no `ref_year` property, so one of them is shown. `river_flood` has rcp26, rcp60 and rcp85 but no rcp45, so rcp60 is shown.

| Label | `frequency` | Sum (per year) | `date` | `event_name` | `orig` true | Ensemble link |
|---|---|---|---|---|---|---|
| RW present | not uniform: 1/451 (40,634), 1/341 (2,893), 1/88 (33); the events with wind in JAM are all 1/451 | 98.96 | Parent's date, 1980-01-02 to 2020-12-25, 41 calendar years | `<IBTrACS sid>`, `<sid>_gen<m>`, m = 1 to 10 | 3,960 (member 0) | 3,960 parents × 11; a member's date and frequency equal its parent's; members adjacent in the file |
| RW rcp45 2060 | not uniform: 17 values, about 1/927 to 1/88; the events with wind in JAM are all 1/451 | 94.57 | As above | As above | 3,960 | 3,960 × 11; 375 parents have members with different frequencies |
| RW rcp85 2060 | not uniform: 17 values, about 1/6,500 to 1/88; the events with wind in JAM are all 1/451 | 90.08 | As above | As above | 3,890 | 3,890 × 11; 361 parents have members with different frequencies; members not always adjacent |
| TC observed | not uniform: 1/41 (3,620), 1/31 (267), 1/8 (3); with wind in JAM all 1/41 | 97.28 | 41 calendar years | `<IBTrACS sid>` | all | none |
| STORM present | uniform, 1/10,000 | 71.28 | First of a month in 1980 only: 12 distinct values, no year | `STORM_DATA_IBTRACS_<basin>_1000_YEARS_<k>.txt-<y>-<n>`, k = 0 to 9, y = 0 to 999 | all | none; the 10,000 years are (k, y) |
| STORM rcp85 | uniform, 1/10,000 | 69.43 | As above | `STORM_DATA_<gcm>_<basin>_1000_YEARS_<k>_IBTRACSDELTA.txt-<y>-<n>` | all | none |
| Flood hist | uniform, 1/920 | 1.00 | 2 July of each year, 1980 to 1999 | `<year>_<model>_<forcing>` | 0 | 46 members (model × forcing) × 20 years; one event per member and year |
| Flood rcp60 | uniform, 1/480 | 1.00 | 2 July of each year, 2050 to 2069 | As above | 0 | 24 members × 20 years |
| Earthquake | uniform, 1/114 | 365.9 | Event dates, 1904-04-04 to 2017-12-30, 114 calendar years | numeric id | all (the dataset description mentions 9 synthetic events per record; the file marks none) | none in the names |
| Wildfire | uniform, 1/20 | 1.00 | 1 January of each year, 2001 to 2020 | the year | all | none; one event per year |
| Windstorm | uniform, 1/2,190 | 1.95 | Parent's date, 1940-11-01 to 2013-12-05; 65 distinct calendar years, span 74 | integer `parent × 100 + m`, m = 0 to 29; `event_id` equals the name | 142 (m = 0) | 142 parents × 30; a member's date equals its parent's |

Two more facts on these datasets:

- The non-uniform frequencies of RW present and TC observed go with the genesis position in the storm ids: 1/341 and 1/31 are 31-year periods (storms from 1990 on, genesis around 80°E to 90°E, North Indian), and 1/88 and 1/8 are 8-year periods (three storms, 2004 to 2011, South Atlantic).
- The flood file for Jamaica has depths of at most 1.2e-7 m, stored on 5 of 542 centroids. Its structure is the same as elsewhere, but its values carry no information.

## Q3. Which annual route fits which hazard?

Three routes:

- **Catalogue years**: the prototype's route. Every event gets a simulation year, and every year is an outcome.
- **`yearsets`**: draw Poisson(λ) events per year from the event set, `sample_events` with replacement.
- **Neither**: the structure supports neither without a decision.

**Setup.** The same data and script as Q2. Year labels per event: `date` for TC observed, earthquake and wildfire; `year + member × span` for the ensembles (the member from `_gen<m>`, `<model>_<forcing>` or `name mod 100`); `k × 1000 + y` from the STORM names. Windstorm uses a season year (July to June). "Proxy" is a stand-in loss with no economic meaning: the sum of the intensity at the three centroids of largest mean intensity. `yearsets` used 20,000 sampled years, λ = the sum of the file's frequencies, with an own generator (seed 311, Q4).

"Prototype, as is" means `ParametricIndex.from_hazard(hazard, exposures)` with no year arguments, then `outcome_measure(..., basis="annual")` on the whole file, or on the events with intensity. "Prototype, labels" passes the year labels with `n_years` and `first_year=0`. The default route takes years from `date`, and the labels route is the array route.

| Hazard | Prototype, as is | Prototype, labels (events with intensity) | Outcomes with labels | Events with intensity per year (variance / mean) | Share of years with zero proxy: catalogue, `yearsets` | Proxy q99: catalogue, `yearsets` |
|---|---|---|---|---|---|---|
| RW present | Whole file raises (frequencies differ). Events with intensity: accepted with a warning; the 11 members of a calendar year are summed into that year (22 outcomes out of 451) | OK, N = 451 | 131 | 0.35 (1.05) | 0.754, 0.764 | 193, 218 |
| RW rcp45 2060 | As above | OK | 131 | 0.35 (1.05) | 0.754, 0.768 | 201, 216 |
| RW rcp85 2060 | As above | OK | 131 | 0.35 (1.05) | 0.754, 0.763 | 207, 234 |
| TC observed | Whole file raises. Events with intensity: accepted, warns on the span | OK, N = 41 | 12 | 0.32 (0.99) | 0.732, 0.743 | 196, 241 |
| STORM present | Accepted with a warning; all events land in the year 1980 (2 outcomes out of 10,000) | OK, N = 10,000 | 3,454 | 0.42 (1.00) | 0.699, 0.703 | 250, 254 |
| STORM rcp85 | As above | OK | 3,979 | 0.50 (0.98) | 0.659, 0.660 | 255, 263 |
| Flood hist | Accepted with a warning; the 46 members of a calendar year are summed (21 outcomes out of 920) | OK, N = 920 | 920 | 1.00 (0) | 0, 0.369 | not meaningful (depths of 1e-7 m) |
| Flood rcp60 | Accepted with a warning (21 outcomes out of 480) | OK, N = 480 | 480 | 1.00 (0) | 0, 0.369 | not meaningful |
| Earthquake | OK, N = 114 | OK | 16 | 0.14 (0.98) | 0.877, 0.877 | 20.0, 20.3 |
| Wildfire | OK, N = 20 | OK | 20 | 1.00 (0) | 0, 0.369 | 1,011, 3,008 |
| Windstorm | Accepted with a warning; 66 outcomes out of 2,190 | Raises: 74 seasons in the dates against 73 from `1 / (frequency × 30)`, so frequency × N = 1.0137 | n/a | 1.92 (0.93) | 0.122, 0.142 | 445, 369 |

Observations:

- **`1 / frequency` is not one number on the whole file for any tropical-cyclone dataset except STORM.** The events with wind in Jamaica all have 1/451 in each RW file and 1/41 in TC observed, and the other values are on events that do not reach Jamaica. Other countries were not checked.
- **For the RW future files, frequency also varies between members of the same parent**, so `1 / frequency` is not a catalogue length there.
- **Hazards with one event per year or per member and year** (flood, wildfire) have no year without an event in the catalogue. Poisson(1) sampling gives 36.9 % of years without one.
- **STORM, flood and windstorm through the prototype's default date route give a much smaller number of distinct outcomes than the years they represent** (2 of 10,000; 21 of 920; 66 of 2,190). The only signal is a logged warning, and the default is accepted. The labels route works (except for windstorm), but only by passing an array built from the names, which the prototype's own `event_year="event_name"` route cannot read: it needs names of the form `<prefix>_<year>_<number>`.
- **Windstorm.** The ensemble labels raise, because the file's frequency implies 73 seasons and its dates reach 74. The dates include a few events in the summer months.
- **Ensembles and the 70/30 year split.** With `year + member × span` labels, splitting the labelled years 70/30 leaves events of the same parent on both sides: 85.7 % of the test events with wind have their parent in the training years for RW, 100 % for windstorm.

What the two routes did on each hazard, from the table above. The choice of a route per hazard is left to the ADR.

| Hazard | Catalogue years | `yearsets` (with replacement) |
|---|---|---|
| RW (present and future) | Runs on the events with wind, with an array of labels (N = 451). Members act as extra years, and parents leak across a year split | Runs on the whole file. Mean and q90 close to the catalogue, q99 13 % higher (present) |
| TC observed | Runs on the events with wind, 41 years | Runs; q99 241 against 196 |
| STORM | Runs with labels from the names, 10,000 years; `date` carries no year | Runs; q99 254 against 250 |
| Flood | Runs with labels, each event a whole member-year | Runs, but 36.9 % of years are empty against none in the catalogue |
| Earthquake | Runs with `date`, 114 years | Runs; q99 20.3 against 20.0 |
| Wildfire | Runs with `date`, 20 years | Runs, but 36.9 % of years are empty against none; q99 3,008 against 1,011 |
| Windstorm | Does not run as labelled: the dates cover 74 seasons and the frequency implies 73 | Runs; q99 369 against 445, share of zero-proxy years 0.142 against 0.122 |

## Q4. `yearsets` as an outcome route

**Setup.** Synthetic `Impact` with 2,000 events and λ = 2 events per year, severity Pareto with shape 1.5. Case "uniform": every frequency 1/1000. Case "non-uniform": frequency inversely proportional to severity (max/min = 189), so rare events are large. Reference: an exact compound Poisson simulation over 400,000 years. Environment `6.2.0`, seed 311. `python packages/climada/scripts/k12_yearsets.py --out yearsets.json`

**`sample_events` with non-uniform frequencies.** Reference: mean 3.30, VaR99 13.19, CVaR99 18.17 (annual).

| Sampled years | Replacement | Warned | Mean | VaR99 | CVaR99 | `correction_fac` value | VaR99, CVaR99 after correction | Realised / nominal occurrence rate: lowest, highest frequency decile |
|---|---|---|---|---|---|---|---|---|
| 200 | no (default) | yes | 3.24 | 11.94 | 14.43 | 1.020 | 12.18, 14.72 | 0.63, 1.19 |
| 200 | yes | no | 3.63 | 15.55 | 23.97 | 0.911 | 14.17, 21.83 | 1.93, 1.04 |
| 2,000 | no (default) | yes | 5.17 | 35.29 | 61.69 | 0.640 | 22.57, 39.45 | 6.00, 0.63 |
| 2,000 | yes | no | 3.33 | 13.84 | 19.26 | 0.993 | 13.75, 19.13 | 1.16, 1.01 |
| 20,000 | no (default) | yes | 5.59 | 39.87 | 92.19 | 0.591 | 23.56, 54.48 | 7.28, 0.63 |
| 20,000 | yes | no | 3.31 | 13.21 | 18.47 | 0.998 | 13.19, 18.44 | 1.01, 0.98 |

Without replacement the pool is cycled, so once it has been exhausted every event has about the same chance, whatever its frequency. The rarest decile is then drawn 6 to 7 times too often and the most frequent 0.63 times as often. Uniform frequencies were not distorted (ratios 0.99 to 1.00 at 2,000 years and above, no warning).

**`correction_fac` and the tail metrics.** The non-uniform case, sampled with replacement, 200 replicates per row. Error relative to the reference, as mean error / RMSE:

| Sampled years | Factor p05, p50, p95 | Mean, raw | Mean, corrected | VaR99, raw | VaR99, corrected | CVaR99, raw | CVaR99, corrected |
|---|---|---|---|---|---|---|---|
| 200 | 0.91, 1.01, 1.09 | −0.1 % / 6.1 % | 0.0 % / 0.0 % | −4.3 % / 15.6 % | −4.4 % / 13.4 % | −2.0 % / 41.5 % | −3.0 % / 35.6 % |
| 1,000 | 0.95, 1.00, 1.04 | 0.1 % / 2.9 % | 0.0 % / 0.0 % | −0.6 % / 7.6 % | −0.7 % / 6.6 % | −2.2 % / 16.4 % | −2.4 % / 14.8 % |
| 10,000 | 0.99, 1.00, 1.02 | −0.1 % / 0.9 % | 0.0 % / 0.0 % | −0.2 % / 2.5 % | −0.1 % / 2.2 % | −0.4 % / 6.0 % | −0.3 % / 5.5 % |

`correction_fac` multiplies every sampled year by one number. It forces the mean to the input's expected annual impact, and it changes the tail RMSE by less than the mean. It does not repair a distorted sample: on the default route at 20,000 years it corrects the mean and leaves CVaR99 at 54.48 against 18.17. `impact_yearset_from_sampling_vect` returns only annual totals (`at_event`, no `imp_mat`), so a design that needs event-level payouts has to work from `sampling_vect`.

**Seeding.** Checked with `np.random.get_state()` before and after each call:

| Call | Result |
|---|---|
| `sample_from_poisson(seed=7)` | changes the global state (it calls `np.random.seed`) |
| `sample_from_poisson(seed=None)` | consumes the global state |
| `sample_events(per_year, freq, seed=<Generator>)` with a `Poisson` count from the same `Generator`, then `impact_yearset_from_sampling_vect(...)` | leaves the global state untouched; the same `sampling_vect`, and the same totals as `compute_imp_per_year` |

`sample_events` passes `seed` to `default_rng`, which accepts a `Generator`. So the seeded route without the global state is: draw the counts with your own generator, pass the generator to `sample_events`, and consume the result through `impact_yearset_from_sampling_vect` or `compute_imp_per_year`. A `sampling_vect` holds **positions** in the event arrays, not event ids (checked with non-consecutive ids), although its docstring says event ids.

**Splitting years so that no event is on both sides.** Non-uniform case, 10,000 sampled years, 70/30, 200 parents of 10 members. Share of test draws whose event (or parent) also appears on the training side:

| Split | Events | Parents |
|---|---|---|
| Split the sampled years | 99.3 % | 100 % |
| Disjoint pools of events, then sample each side | 0 % | 100 % |
| Disjoint pools of parents, then sample each side | 0 % | 0 % |

A pool's frequencies are rescaled by its share of the total (test pool: 30 % of the frequency), so that both sides keep λ = 2. In the parent-pool case the two sides' annual metrics are: mean 3.38 and 3.25, CVaR99 18.6 and 15.6 (not the same pool). With catalogue years the same parent appears in several member blocks (Q3), so a year split alone does not separate parents.

## Q5. Scale of the design LP

**Setup.** The prototype's own linear program, through its `solve_design`: one joint problem over all units, weighted CVaR with `alpha = 0.9`, `beta = 0.95`, pure premium, budget 1.0, 5 steps, annual basis. The data are synthetic and built as the large case: every event has a loss, so no shortfall variable is dropped. An event touches `max(1, ceil(0.05 × units))` adjacent units, its index is uniform on 25 to 80 and its loss is `(index − 25)²` times lognormal(0, 0.5) noise, with two events per simulation year on average. Each configuration runs in a process of its own, and its peak resident memory is its own. Other jobs of this spike ran at the same time, so the timings are upper bounds of a kind, not benchmarks.

```
python packages/climada/scripts/k12_lp_scale.py --out lp.json --timeout 2400
python packages/climada/scripts/k12_lp_scale.py --units 1000 --events 10000 50000 --method highs-ipm --out ipm.json --timeout 1800
```

**Time and memory, environment `6.2.0` (scipy 1.17.1, HiGHS 1.12.0 inside).** `method="highs"` is what the prototype uses and leaves the choice of algorithm to HiGHS. `highs-ipm` is the interior-point method, with HiGHS's default crossover setting; it was run where the default was slow.

| Units × events | Variables (about) | Outcomes | Dense inputs (MB) | `method` | Solve (s) | HiGHS (s) | `linprog` around HiGHS (s) | Peak RSS (MB) |
|---|---|---|---|---|---|---|---|---|
| 1 × 10,000 | 14,329 | 4,322 | 0.15 | `highs` | 0.27 | 0.25 | 0.02 | 195 |
| 1 × 50,000 | 71,717 | 21,710 | 0.76 | `highs` | 6.8 | 6.7 | 0.08 | 398 |
| 67 × 10,000 | 14,688 | 4,351 | 10.2 | `highs` | 6.4 | 6.4 | 0.02 | 224 |
| 67 × 50,000 | 71,996 | 21,659 | 51 | `highs` | 127 | 127 | 0.09 | 410 |
| 67 × 50,000 | 71,996 | 21,659 | 51 | `highs-ipm` | 36 | 36 | 0.15 | 424 |
| 1,000 × 10,000 | 19,298 | 4,296 | 153 | `highs` | not solved in 2,400 s | | | |
| 1,000 × 10,000 | 19,298 | 4,296 | 153 | `highs-ipm` | 59 | 59 | 0.10 | 787 |
| 1,000 × 50,000 | 76,575 | 21,573 | 763 | `highs` | stopped by hand after about 10 minutes, once 1,000 × 10,000 had hit its limit | | | |
| 1,000 × 50,000 | 76,575 | 21,573 | 763 | `highs-ipm` | 410 | 409 | 0.46 | 1,572 |

On 67 × 50,000 the two methods' objective values agree to every printed digit (6479.525753749786). "Dense inputs" are the index and loss arrays of the prototype's `DesignData`, which are dense; the peak memory is otherwise mostly HiGHS and the assembly.

**Is the overhead after HiGHS returns gone?** The time `linprog` spends outside `Highs.run`, in seconds, for the same LP. HiGHS itself took 0.1 to 6 s in these runs.

| Units × events | Variables (about) | scipy 1.15.2 (conda-forge) | scipy 1.15.2 (PyPI) | 1.15.3 (PyPI) | 1.16.3 (PyPI) | 1.17.1 (PyPI) | 1.18.1 (PyPI) |
|---|---|---|---|---|---|---|---|
| 1 × 4,000 | 5,740 | 49.7 | 49.6 | 0.02 | 0.05 | 0.02 | 0.02 |
| 67 × 10,000 | 14,688 | 65.8 | 66.4 | 0.02 | 0.02 | 0.02 | 0.02 |
| 1 × 20,000 | 28,672 | 972 | 668 | 0.06 | 0.06 | 0.04 | 0.05 |

The overhead is present in scipy 1.15.2 and absent from 1.15.3 on, on both conda-forge and PyPI builds of 1.15.2. The difference in the source is one line of `optimize/_highspy/_highs_wrapper.py`: 1.15.2 reads `basis.col_status[ii]` inside its loop over the variables, and the 1.15.3 wheel and conda-forge's 1.17.1 read `basis.col_status` once before the loop (the other versions' sources were not read). conda-forge has no 1.15.3 (`pixi search -c conda-forge "scipy 1.15.*"` ends at 1.15.2), so CLIMADA 6.1's pin resolves to the slow version, as this repository's lock does; CLIMADA 6.2.0's pin is `scipy 1.17.*`. The growth with the number of variables is not a clean square in these runs (other jobs were running), but the overhead reaches about 11 minutes or more at 28,672 variables.

## Q6. The MSE route without a new package

**Setup.** The problem is `min Σ_o p_o (L_o − P_o)²` over the payout levels, with `0 ≤ level ≤ cap`, monotone levels and the premium budget. Annual basis, 5 steps, one joint design problem over all units, pure premium, budget 0.8 (it binds: the multiplier found is 0.107, 0.290 and 0.222 on the first three sizes). The data are the synthetic generator of Q5, where every event has a loss. Environment `6.2.0`: scipy 1.17.1 (HiGHS 1.12.0 inside), highspy 1.15.1, cvxpy 1.9.3. Each run is its own process, with a timeout of 600 s, while other jobs of this spike were running.

```
python packages/climada/scripts/k12_mse_routes.py --out mse.json --timeout 600
```

The reference is the prototype's own route, cvxpy with Clarabel at tolerances of `1e-10`. The options of the others: `trust-constr` `gtol` `1e-9`, `xtol` `1e-12`, `barrier_tol` `1e-9`; `SLSQP` `ftol` `1e-13`; `lsq_linear` `trf` with `lsmr`, `tol` `1e-12`, on the level increments, with Brent's method on the budget's multiplier. `lsq_linear` takes bounds only, so its cap is a bound on each increment; no route's result broke a bound, the monotonicity or the budget by more than `1e-15`.

Cells are wall time and the objective's relative gap to cvxpy on the same data (negative: below cvxpy's value). The levels are per unit and step (`n_units × 5`).

| Route | New package | 1 × 10,000 (5 levels) | 67 × 10,000 (335) | 67 × 50,000 (335) | 1,000 × 10,000 (5,000) |
|---|---|---|---|---|---|
| cvxpy with Clarabel (reference) | cvxpy | 0.58 s | 0.55 s | 1.25 s | 14.0 s |
| `highspy` QP | highspy | 0.015 s, −3e-12 | 0.042 s, −2e-11 | 0.051 s, −1e-11 | 37.5 s, −7e-11 |
| scipy's private HiGHS bindings, QP | none (private module) | 0.001 s, −3e-12 | 0.034 s, −2e-11 | 0.040 s, −1e-11 | 42.3 s, −7e-11 |
| `scipy.optimize` `trust-constr` | none | 0.022 s, 1.2e-5 | 0.25 s, 2.1e-5 | 0.33 s, 1.8e-5 | 53.3 s, 1.4e-3 |
| `scipy.optimize` `SLSQP` | none | 0.001 s, −3e-12 | 1.41 s, −2e-11 | 1.03 s, −1e-11 | not done in 600 s |
| `lsq_linear` with a multiplier on the budget | none | 0.063 s, −3e-12 | 51.0 s, 4e-9 | 157 s, 7e-10 | not done in 600 s |

Peak resident memory is 144 to 354 MB on the first three sizes. On 1,000 × 10,000 it is 974 MB (cvxpy), 1,654 MB (`highspy`), 1,743 MB (private bindings) and 896 MB (`trust-constr`).

With a **cost-of-capital load** (rate 0.3, q 0.99; the premium needs auxiliary variables, one per outcome with a payout), only cvxpy and `highspy` were run, because the other routes have no linear rows for these auxiliaries here:

| Size | cvxpy | `highspy` |
|---|---|---|
| 1 × 10,000 | 1.19 s | 0.15 s, gap −1.2e-10 |
| 67 × 10,000 | 1.89 s | not done in 600 s |

Facts on the dependency side:

- Neither cvxpy nor highspy is a dependency of CLIMADA (Q1). Petals' `pyproject.toml` at develop `3f57dcf` has no optional-dependencies table.
- scipy bundles HiGHS: 1.8.0 in scipy 1.15.2 and 1.15.3, 1.12.0 in 1.17.1 and 1.18.1. The bindings `scipy.optimize._highspy._core` expose `HighsHessian` and `passHessian` in those four versions (1.16.3 not checked). The module name starts with an underscore, so it is not scipy's public interface.
- `linprog` itself has no quadratic term, so the private bindings are the only way into that solver from scipy alone.
- `pymoo`, the one solver package petals requires, is a genetic-algorithm library and was not tried here.

## Q7. The zero-basis-risk trap

**Setup (every number in this section).** One unit, individual scope, annual basis, out of sample. 6,000 synthetic straight storms over 3,000 simulation years, frequency 1/3,000 each; the first 2,100 years calibrate and the last 900 are the test. Tracks within 1.5° of latitude of the site, near Miami; every storm gives wind above 25 m/s at the site, so every event has a loss. Value USD 1e9, Emanuel `v_half` 74.7 m/s, `v_thresh` 25.7 m/s. Pure premium, budget 1.0, objective the expected uncovered loss `E[U]`. Step payout uniform on `[25, 85)` m/s, K steps. Cat-in-a-circle radius 50 km; the category index uses categories 1 to 5. Environment `6.2.0`, seed 311, `python packages/climada/scripts/k12_zero_basis.py --out zero.json`.

Reported: `E[U]/E[L]` and `CVaR95(U)/CVaR95(L)` on the test years (`CVaR95` of annual values). `E[L]` on the test years is USD 83.9M a year for the one-point setups (87.6M with the `v_half` draws) and 83.4M (0.1° grid) and 75.8M (0.5° grid) for the units.

| Setup | Spearman(index, loss) | K = 5 | K = 10 | K = 20 | K = 40 | K = 80 |
|---|---|---|---|---|---|---|
| One point, centroid wind, one impact function | 1.000 | 0.141 / 0.220 | 0.092 / 0.136 | 0.050 / 0.067 | 0.023 / 0.033 | 0.012 / 0.017 |
| 25 points on a 0.1° grid, wind at the central point | 0.999 | 0.136 / 0.218 | 0.082 / 0.129 | 0.043 / 0.063 | 0.025 / 0.037 | 0.018 / 0.026 |
| Same, mean wind of the 25 points | 1.000 | 0.145 / 0.215 | 0.085 / 0.123 | 0.043 / 0.060 | 0.024 / 0.033 | 0.014 / 0.023 |
| 25 points on a 0.5° grid, wind at the central point | 0.940 | 0.059 / 0.094 | 0.045 / 0.098 | 0.039 / 0.080 | 0.039 / 0.082 | 0.040 / 0.082 |
| Same, mean wind of the 25 points | 0.956 | 0.060 / 0.087 | 0.047 / 0.083 | 0.037 / 0.067 | 0.034 / 0.069 | 0.033 / 0.066 |
| One point, centroid wind, `v_half` drawn per event (uniform on 60 to 95 m/s) | 0.921 | 0.293 / 0.439 | 0.266 / 0.411 | 0.256 / 0.387 | 0.255 / 0.381 | 0.257 / 0.385 |
| Cat-in-a-circle, wind within 50 km (`max_wind`) | 0.637 | 0.463 / 0.610 | 0.463 / 0.610 | 0.463 / 0.610 | 0.463 / 0.610 | 0.463 / 0.610 |
| Cat-in-a-circle, Saffir-Simpson category | 0.530 | 0.563 / 0.702 (5 steps, categories 1 to 5) | | | | |

Cells are `E[U]/E[L]` / `CVaR95(U)/CVaR95(L)`.

Observations:

- **One exposure point, a centroid index and one impact function:** the loss is an exact function of the index, and `E[U]/E[L]` falls from 14.1 % (K = 5) to 1.2 % (K = 80), roughly halving with each doubling of K from K = 10 on.
- **A unit of several points does not by itself remove the effect.** A 0.1° grid (±0.2°, about ±22 km around the centre) keeps Spearman at 0.999 and about the same decay with K. A 0.5° grid (±1.0°, about ±110 km) has a floor of about 3.3 % to 4 % from K = 20.
- **`v_half` draws** hold a floor of about 25.5 % from K = 20, with Spearman 0.92.
- **Cat-in-a-circle** at 50 km gives 46 % and 56 %. Over all events, 41 % of the loss is on events with no track point inside the circle, which have index 0 and get no payout.

Details that bear on reading the table: on the two cat-in-a-circle rows every step pays the cap (the largest training loss) and the budget does not bind (premium 0.71 and 0.86 of `E[L]`), which is why the wind row does not change with K. All other rows use the whole budget (premium 1.00 of `E[L]`). No objective other than `E[U]` was run, and nothing here compares objectives or calibration scopes.

## Q8. `climada_petals.engine.cat_bonds` (petals 6.2.0)

**Setup.** Environment `dev` (the `cat_bonds` code is identical to `v6.2.0`). Synthetic exposures on a 0.1° grid and a hazard with centroids on the exposure points. `python packages/climada/scripts/k12_cat_bonds.py --out cat_bonds.json`. The module makes parametric cat-bond structures per subarea of a country's exposed area. The questions here are only about using its pieces.

**`Subareas` as a source of units.**

| Check | Result |
|---|---|
| `from_resolution` on a 12 × 12 grid, resolution 0.3° | 16 subareas with 9 exposure points each; each point is in exactly one subarea |
| `subareas_gdf` columns | `geometry` and `subarea_letter` only; there is no point-to-subarea column, so a spatial join is needed (done here with `sjoin`) |
| `subarea_letter` for 900 subareas (`chr(65 + i)`) | all 900 are unique; the 27th is `[` and the last is `τ`, so the labels stop being letters after 26 |
| `from_resolution` with one exposure point | raises `ValueError` from `NearestNeighbors` |
| `from_resolution` with three scattered points | 3 subareas |
| `from_geodataframe`, a `MultiPolygon` | raises `ValueError` (polygons only) |
| `from_geodataframe`, a polygon not covering the exposure, one covering only part of it | no error in either case (the coverage check compares `numpy.bool_` to `False` with `is`) |

`Subareas` holds polygons. An index per subarea is the mean or a percentile of the intensity over the hazard centroids in the polygon (`_calc_parametric_index`). So it can supply a grouping of points into units, through a spatial join, but not a unit that is one exposure point.

**Does `calc_payout` equal a linear payout with the same parameters?** On 100,004 float intensities (including the triggers) against `max_pay * clip((x - min_trig) / (max_trig - min_trig), 0, 1)`, with `min_trig = 30`, `max_trig = 60`, `max_pay = 1e6`: the largest absolute difference is 0.0, the payout at `min_trig` is 0 and at `max_trig` is `max_pay`.

Two edge cases:

- An integer-typed index truncates: `np.zeros_like` inherits the integer type, so categories 0 to 5 with triggers 1 and 4 and `max_pay` 1,000,000.5 give `[0, 0, 333333, 666667, 1000000, 1000000]` against `[0, 0, 333333.5, 666667, 1000000.5, 1000000.5]`. The module's own `_calc_pay_vs_dam` builds floats, and its index is a float mean or percentile.
- With `min_trig > max_trig` it pays `max_pay` for every intensity at or above `max_trig` and nothing below it: the optimiser (COBYLA) is unconstrained, so this can occur.

## Not answered, and limits

- `linux-64` was not tested in any environment. Everything ran on osx-arm64.
- Timings come from one shared machine, and each configuration was timed once.
- Q2 and Q3 cover one country per hazard. The uniform frequencies among the events that reach Jamaica need not hold elsewhere. Whether a route fits a hazard depends on how the hazard was built; only the structure above was checked.
- Q7 uses synthetic, nearby storms, one site and one objective; no real exposure or hazard catalogue was used.
- The proxy loss of Q3 has no economic meaning. It only shapes the comparison between routes.
