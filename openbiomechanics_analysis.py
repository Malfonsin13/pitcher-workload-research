"""
openbiomechanics_analysis.py
============================

This module provides helper functions for exploring and analysing the open
biomechanics pitching data published by Driveline Baseball.  It is designed
to be executed from a Jupyter notebook (for example, in Google Colab) and
assumes that the user has an internet connection to download the data
directly from the project’s GitHub repository.

The core of the dataset is contained in the point‑of‑interest (POI) CSV.
The README of the OpenBiomechanics Project explains that this table
contains “kinematic, kinetic, and energetic metrics commonly referenced in
biomechanical analyses” and that variables are suffixed with markers
identifying the event in the pitching motion at which the measurement
occurs【486266223109195†L202-L241】.  For example, variables ending in
``_fp`` correspond to values at foot plant, ``_mer`` to maximum external
rotation and ``_br`` to ball release.  Ground reaction forces and
energetics are also included【486266223109195†L290-L331】.

This script downloads the POI metrics and associated metadata, creates
velocity buckets, and exposes helper functions to explore relationships
between variables and pitch velocity.  It focuses on correlation
visualisation: scatter plots coloured by velocity bucket, correlation
coefficients between variables, and correlations between derived quantities
(ratios and differences) and pitch speed.  A high‑level function is also
provided to iterate over all pairs of variables associated with a given
event suffix and summarise their correlations.

Usage
-----
```
!pip install pandas matplotlib seaborn requests
import openbiomechanics_analysis as obp

# download data
poi, meta = obp.load_data()

# categorise velocities (adds ``velocity_bucket`` column to ``poi``)
poi = obp.add_velocity_buckets(poi)

# analyse a specific pair of variables and plot their relationship
obp.analyse_pair(poi,
                 var1='pelvis_anterior_tilt_fp',
                 var2='torso_anterior_tilt_fp',
                 save_plot=False)

# automatically analyse all pairs of foot‑plant variables
summary_df = obp.analyse_event_pairs(poi, event_suffix='fp')
summary_df.head()
```

Copyright
---------
The OpenBiomechanics dataset is provided under a Creative Commons
Attribution–NonCommercial–ShareAlike licence with additional restrictions
on use by professional sports organisations【685456047408860†L29-L45】.  The code
herein is distributed under the same licence terms.
"""

import io
import itertools
import os
from typing import Iterable, Tuple, List

import matplotlib.pyplot as plt
import pandas as pd
import requests
import seaborn as sns
from pandas import DataFrame


def load_data(
    poi_url: str = (
        "https://raw.githubusercontent.com/drivelineresearch/openbiomechanics/main/"
        "baseball_pitching/data/poi/poi_metrics.csv"
    ),
    metadata_url: str = (
        "https://raw.githubusercontent.com/drivelineresearch/openbiomechanics/main/"
        "baseball_pitching/data/metadata.csv"
    ),
    force_download: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Download and return the POI metrics and metadata tables.

    Parameters
    ----------
    poi_url : str, optional
        URL of the point‑of‑interest CSV file.  The default points to the
        Driveline GitHub repository.
    metadata_url : str, optional
        URL of the metadata CSV file.  Contains session and player level
        information (height, mass, age, playing level and pitch speed).
    force_download : bool, optional
        Always download from the remote URL.  If ``False`` and cached copies
        of the files exist in the current working directory, they will be
        loaded instead.  Defaults to ``True``.

    Returns
    -------
    Tuple[pandas.DataFrame, pandas.DataFrame]
        The POI metrics DataFrame and the metadata DataFrame.

    Notes
    -----
    GitHub uses Git LFS to store large files.  Downloading via ``requests``
    instead of direct git clone circumvents issues with LFS pointers.
    """
    poi_path = os.path.join(os.getcwd(), "poi_metrics.csv")
    meta_path = os.path.join(os.getcwd(), "metadata.csv")

    if not force_download and os.path.exists(poi_path) and os.path.exists(meta_path):
        poi = pd.read_csv(poi_path)
        meta = pd.read_csv(meta_path)
        return poi, meta

    # Helper to stream download large CSVs
    def _download_csv(url: str, local_path: str) -> pd.DataFrame:
        resp = requests.get(url, stream=True)
        resp.raise_for_status()
        content = io.BytesIO(resp.content)
        df = pd.read_csv(content)
        df.to_csv(local_path, index=False)
        return df

    poi = _download_csv(poi_url, poi_path)
    meta = _download_csv(metadata_url, meta_path)
    return poi, meta


def add_velocity_buckets(df: DataFrame, speed_column: str = "pitch_speed_mph") -> DataFrame:
    """Add a categorical velocity bucket based on pitch speed.

    Four buckets are defined:
    
    * ``'>94'`` for velocities ≥ 94 mph
    * ``'91–93.99'`` for velocities ≥ 91 mph and < 94 mph
    * ``'88–90.99'`` for velocities ≥ 88 mph and < 91 mph
    * ``'<88'`` for velocities < 88 mph

    Parameters
    ----------
    df : pandas.DataFrame
        DataFrame containing a numeric pitch speed column.
    speed_column : str, optional
        Name of the column containing pitch speeds.  Defaults to
        ``'pitch_speed_mph'``.

    Returns
    -------
    pandas.DataFrame
        The input DataFrame with an additional ``velocity_bucket`` column.
    """
    def _bucket(speed: float) -> str:
        if pd.isna(speed):
            return 'Unknown'
        if speed >= 94:
            return '>94'
        elif speed >= 91:
            return '91–93.99'
        elif speed >= 88:
            return '88–90.99'
        else:
            return '<88'

    df = df.copy()
    df["velocity_bucket"] = df[speed_column].apply(_bucket)
    return df


def analyse_pair(
    df: DataFrame,
    var1: str,
    var2: str,
    speed_var: str = "pitch_speed_mph",
    hue: str = "velocity_bucket",
    save_plot: bool = False,
    output_dir: str = "plots",
) -> Tuple[float, float, float]:
    """Visualise and quantify the relationship between two variables.

    A scatter plot coloured by velocity bucket is produced.  Pearson
    correlation coefficients are computed between the two variables, between
    their ratio (``var1 / var2``) and pitch speed, and between their
    difference (``var1 – var2``) and pitch speed.  Missing values are
    dropped on a per‑row basis before analysis.

    Parameters
    ----------
    df : pandas.DataFrame
        The data table containing the variables.
    var1, var2 : str
        Names of the columns to analyse.
    speed_var : str, optional
        Name of the column containing pitch speeds.  Defaults to
        ``'pitch_speed_mph'``.
    hue : str, optional
        Name of the categorical column used to colour points.  Defaults to
        ``'velocity_bucket'``.
    save_plot : bool, optional
        If ``True``, the plot will be saved to ``output_dir``.  The
        filename is derived from the variable names.  Defaults to ``False``.
    output_dir : str, optional
        Directory into which plots are saved when ``save_plot`` is ``True``.

    Returns
    -------
    Tuple[float, float, float]
        A tuple containing three correlation coefficients:

        1. correlation between ``var1`` and ``var2``
        2. correlation between the ratio ``var1 / var2`` and ``speed_var``
        3. correlation between the difference ``var1 – var2`` and ``speed_var``

    Notes
    -----
    Correlations are computed using pandas’ default Pearson method.  If
    fewer than two non‑missing rows exist, all correlations will be
    returned as NaN.
    """
    subset = df[[var1, var2, speed_var, hue]].dropna()
    if subset.empty or len(subset) < 2:
        return float('nan'), float('nan'), float('nan')

    # compute derived quantities
    subset = subset.copy()
    # protect against division by zero
    subset["ratio"] = subset[var1] / subset[var2].replace({0: pd.NA})
    subset["diff"] = subset[var1] - subset[var2]

    # correlations
    corr_vars = subset[var1].corr(subset[var2])
    corr_ratio_speed = subset["ratio"].corr(subset[speed_var])
    corr_diff_speed = subset["diff"].corr(subset[speed_var])

    # plot
    plt.figure(figsize=(7, 5))
    sns.scatterplot(
        data=subset,
        x=var1,
        y=var2,
        hue=hue,
        palette="viridis",
        alpha=0.7,
    )
    plt.xlabel(var1)
    plt.ylabel(var2)
    plt.title(
        f"{var1} vs {var2}\n"
        f"corr={corr_vars:.2f}, ratio–speed corr={corr_ratio_speed:.2f}, diff–speed corr={corr_diff_speed:.2f}"
    )
    plt.legend(title=hue)
    plt.tight_layout()
    if save_plot:
        os.makedirs(output_dir, exist_ok=True)
        fname = f"{var1}_vs_{var2}.png".replace("/", "_")
        plt.savefig(os.path.join(output_dir, fname), dpi=200)
    plt.show()

    return corr_vars, corr_ratio_speed, corr_diff_speed


def get_event_columns(df: DataFrame, suffix: str) -> List[str]:
    """Return a list of column names ending with a given suffix.

    The OpenBiomechanics POI dataset uses suffixes such as ``_fp``
    (foot plant), ``_mer`` (maximum external rotation), ``_br``
    (ball release) and ``_pkh`` (peak knee height) to indicate the
    event at which a measurement was taken.  This helper filters
    columns based on that suffix.

    Parameters
    ----------
    df : pandas.DataFrame
        DataFrame from which to extract column names.
    suffix : str
        Event suffix (without the underscore).  For example, ``'fp'``.

    Returns
    -------
    List[str]
        A list of matching column names.
    """
    if suffix and not suffix.startswith("_"):
        suffix = "_" + suffix
    return [col for col in df.columns if col.endswith(suffix)]


def analyse_event_pairs(
    df: DataFrame,
    event_suffix: str,
    speed_var: str = "pitch_speed_mph",
    hue: str = "velocity_bucket",
    plot: bool = False,
) -> DataFrame:
    """Compute correlations for all pairs of variables at a given event.

    This function identifies all columns whose names end with the given
    ``event_suffix`` (for example, ``'fp'`` for foot plant) and iterates
    through every unique pair.  For each pair, it calculates the
    correlation between the variables as well as the correlations
    between their ratio/difference and pitch speed, optionally
    generating scatter plots.  Results are returned in a summary
    DataFrame.

    Parameters
    ----------
    df : pandas.DataFrame
        Table containing the variables of interest.  Must already have
        velocity buckets (see :func:`add_velocity_buckets`).
    event_suffix : str
        Suffix identifying the event (``'fp'``, ``'mer'``, ``'br'``, ``'pkh'``).
    speed_var : str, optional
        Name of the pitch speed column.  Defaults to ``'pitch_speed_mph'``.
    hue : str, optional
        Column used to colour scatter plots.  Defaults to ``'velocity_bucket'``.
    plot : bool, optional
        If ``True``, generate a scatter plot for each pair.  Turn off
        plotting for faster summarisation.

    Returns
    -------
    pandas.DataFrame
        A summary table with one row per variable pair.  Columns include
        ``var1``, ``var2``, ``corr_vars``, ``corr_ratio_speed`` and
        ``corr_diff_speed``.
    """
    cols = get_event_columns(df, event_suffix)
    results = []
    for var1, var2 in itertools.combinations(cols, 2):
        corr_v, corr_ratio, corr_diff = analyse_pair(
            df, var1, var2, speed_var=speed_var, hue=hue, save_plot=False
        ) if plot else _analyse_without_plot(df, var1, var2, speed_var)
        results.append(
            {
                "var1": var1,
                "var2": var2,
                "corr_vars": corr_v,
                "corr_ratio_speed": corr_ratio,
                "corr_diff_speed": corr_diff,
            }
        )
    summary = pd.DataFrame(results)
    return summary


def _analyse_without_plot(df: DataFrame, var1: str, var2: str, speed_var: str) -> Tuple[float, float, float]:
    """Internal helper mirroring :func:`analyse_pair` without plotting.

    Parameters
    ----------
    df : pandas.DataFrame
        Input data table.
    var1, var2 : str
        Names of the variables being analysed.
    speed_var : str
        Pitch speed column name.

    Returns
    -------
    Tuple[float, float, float]
        Correlations as described in :func:`analyse_pair`.
    """
    subset = df[[var1, var2, speed_var]].dropna()
    if subset.empty or len(subset) < 2:
        return float('nan'), float('nan'), float('nan')
    subset = subset.copy()
    subset["ratio"] = subset[var1] / subset[var2].replace({0: pd.NA})
    subset["diff"] = subset[var1] - subset[var2]
    corr_v = subset[var1].corr(subset[var2])
    corr_ratio = subset["ratio"].corr(subset[speed_var])
    corr_diff = subset["diff"].corr(subset[speed_var])
    return corr_v, corr_ratio, corr_diff
