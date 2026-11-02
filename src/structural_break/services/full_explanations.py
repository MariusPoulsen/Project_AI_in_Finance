"""Offline, exact interventional linear SHAP for the frozen annual desk stack.

The background is each fit's training mean. The explicit interaction is an input
in its own right; these are not conditional attributions for correlated inputs.
Browsing only consumes the exported tables and never calls ``reconstruct``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

AGENT_FEATURES = (
    "no_news",
    "abstain",
    "explains_move",
    "persistence",
    "relationship_change",
    "persistence_x_explains",
)


def reconstruct(table: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    from sklearn.linear_model import LogisticRegression

    events: list[dict[str, Any]] = []
    values: list[dict[str, Any]] = []
    score = np.clip(table.base_score.to_numpy(float), 1e-6, 1 - 1e-6)
    for name, agents in (("full_base", False), ("full", True)):
        columns = ["logit_bag5", *(AGENT_FEATURES if agents else ())]
        x = np.column_stack(
            [np.log(score / (1 - score)), *[table[c].to_numpy(float) for c in columns[1:]]]
        )
        y = table.y.to_numpy(int)
        for year in sorted(table.year.unique()):
            train, test = table.year.lt(year).to_numpy(), table.year.eq(year).to_numpy()
            if train.sum() < 200 or len(set(y[train])) < 2:
                continue
            mean, std = x[train].mean(0), x[train].std(0) + 1e-9
            model = LogisticRegression(C=1.0, max_iter=2000).fit((x[train] - mean) / std, y[train])
            test_inputs = x[test]
            z = (test_inputs - mean) / std
            contributions = z * model.coef_[0]
            margins = model.decision_function(z)
            probabilities = model.predict_proba(z)[:, 1]
            for i, event in enumerate(table.loc[test].itertuples()):
                events.append(
                    {
                        "model": name,
                        "event_id": event.event_id,
                        "year": int(year),
                        "base": float(model.intercept_[0]),
                        "margin": float(margins[i]),
                        "probability": float(probabilities[i]),
                        "train_n": int(train.sum()),
                        "train_last_year": int(table.loc[train, "year"].max()),
                    }
                )
                for j, feature in enumerate(columns):
                    values.append(
                        {
                            "model": name,
                            "event_id": event.event_id,
                            "feature": feature,
                            "value": float(test_inputs[i, j]),
                            "training_mean": float(mean[j]),
                            "training_std": float(std[j]),
                            "coefficient": float(model.coef_[0, j]),
                            "contribution": float(contributions[i, j]),
                        }
                    )
    return pd.DataFrame(events), pd.DataFrame(values)


def validate(events: pd.DataFrame, values: pd.DataFrame, forecasts: pd.DataFrame) -> None:
    keys = ["model", "event_id"]
    if events.empty or events.duplicated(keys).any() or values.duplicated([*keys, "feature"]).any():
        raise ValueError("Empty or duplicate Full explanations")
    if set(events.model) != {"full", "full_base"}:
        raise ValueError("Invalid stack identities")
    if (
        forecasts.event_id.duplicated().any()
        or not np.isfinite(events[["base", "margin", "probability"]].to_numpy(float)).all()
    ):
        raise ValueError("Invalid published identities or nonfinite Full totals")
    if (
        not np.isfinite(
            values[
                ["value", "training_mean", "training_std", "coefficient", "contribution"]
            ].to_numpy(float)
        ).all()
        or not values.training_std.gt(0).all()
    ):
        raise ValueError("Invalid Full coefficients or training background")
    if not events.train_last_year.lt(events.year).all() or not events.train_n.ge(200).all():
        raise ValueError("Stack explanation chronology differs")
    totals = values.groupby(keys).contribution.sum()
    expected = events.set_index(keys)
    if set(expected.index) != set(totals.index) or not np.allclose(
        expected.margin - expected.base, totals.reindex(expected.index), atol=1e-10
    ):
        raise ValueError("Full explanation additivity failed")
    computed = (values.value - values.training_mean) / values.training_std * values.coefficient
    if not np.isfinite(values.contribution).all() or not np.allclose(
        computed, values.contribution, atol=1e-10
    ):
        raise ValueError("Full explanation coefficients differ")
    if not np.allclose(1 / (1 + np.exp(-events.margin)), events.probability, atol=1e-10):
        raise ValueError("Full explanation probabilities differ")
    published = forecasts.set_index("event_id")
    for model, part in events.groupby("model"):
        target = published.loc[published[f"p_{model}"].notna()]
        if set(part.event_id) != set(target.index):
            raise ValueError("Full explanation population differs")
        target = target.loc[part.event_id]
        if not np.array_equal(part.year, target.year) or not np.allclose(
            part.probability, target[f"p_{model}"], atol=1e-9, rtol=1e-9
        ):
            raise ValueError("Full explanations do not reproduce published scores")
        allowed = {"logit_bag5", *(AGENT_FEATURES if model == "full" else ())}
        fields = values.loc[values.model.eq(model)].groupby("event_id").feature.agg(set)
        if set(fields.index) != set(part.event_id) or not all(s == allowed for s in fields):
            raise ValueError("Full explanation features differ")
