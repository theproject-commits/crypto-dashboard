from datetime import UTC, date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .... import crud, schemas
from ....database import get_db
from ....security import require_auth
from ....services.composite_engine import compute_composite_v1
from ....services.composite_v2_engine import compute_composite_v2
from ....services.market_state_engine import compute_market_state
from .cryptos_research import read_composite_v2_walk_forward
from .cryptos_utils import format_pct as _format_pct, policy_zone as _policy_zone

router = APIRouter()


@router.get("/{coingecko_id}/composite", response_model=schemas.CompositeResponse)
def read_composite_score(
    coingecko_id: str,
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    rows = crud.get_market_composite_history(
        db=db,
        crypto_id=db_crypto.id,
        limit=1,
    )
    if rows:
        row = rows[0]
        return schemas.CompositeResponse(
            coingecko_id=coingecko_id,
            snapshot_date=row.snapshot_date,
            horizon_days=row.horizon_days,
            composite_score=float(row.composite_score),
            label=row.label,
            confidence=float(row.confidence),
            generated_at=row.generated_at,
            components=schemas.CompositeComponents(
                regime_score=float(row.regime_score),
                flow_score=float(row.flow_score),
                sentiment_score=float(row.sentiment_score),
                sentiment_source="baseline",
            ),
        )

    history = crud.get_price_history_all(db, crypto_id=db_crypto.id)
    prices = [float(entry.price_usd) for entry in history]
    volumes = [float(entry.total_volume_usd) for entry in history]
    if len(prices) < 120 or len(volumes) < 120:
        raise HTTPException(status_code=400, detail="Insufficient history for composite score")
    state = compute_market_state(coingecko_id=coingecko_id, prices=prices, volumes=volumes)
    return compute_composite_v1(
        coingecko_id=coingecko_id,
        snapshot_date=history[-1].date,
        state=state,
        prices=prices,
        volumes=volumes,
        horizon_days=30,
    )


@router.get("/{coingecko_id}/composite/history", response_model=List[schemas.CompositeSnapshotResponse])
def read_composite_history(
    coingecko_id: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = Query(default=365, ge=1, le=5000),
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    rows = crud.get_market_composite_history(
        db=db,
        crypto_id=db_crypto.id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    output: list[schemas.CompositeSnapshotResponse] = []
    for row in reversed(rows):
        output.append(
            schemas.CompositeSnapshotResponse(
                snapshot_date=row.snapshot_date,
                horizon_days=row.horizon_days,
                regime_score=float(row.regime_score),
                flow_score=float(row.flow_score),
                sentiment_score=float(row.sentiment_score),
                composite_score=float(row.composite_score),
                label=row.label,
                confidence=float(row.confidence),
                generated_at=row.generated_at,
            )
        )
    return output


@router.get("/{coingecko_id}/composite/v2", response_model=schemas.CompositeV2Response)
def read_composite_score_v2(
    coingecko_id: str,
    horizon_days: int = Query(default=30, ge=7, le=365),
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    history = crud.get_price_history_all(db, crypto_id=db_crypto.id)
    prices = [float(entry.price_usd) for entry in history]
    volumes = [float(entry.total_volume_usd) for entry in history]
    if len(prices) < 180 or len(volumes) < 60:
        raise HTTPException(status_code=400, detail="Insufficient history for composite v2")

    snapshot_date = history[-1].date
    computed = compute_composite_v2(
        coingecko_id=coingecko_id,
        snapshot_date=snapshot_date,
        prices=prices,
        volumes=volumes,
        horizon_days=horizon_days,
    )
    crud.upsert_market_composite_v2_snapshot(
        db=db,
        crypto_id=db_crypto.id,
        snapshot_date=snapshot_date,
        horizon_days=horizon_days,
        regime_score=computed["components"]["regime_score"],
        flow_score=computed["components"]["flow_score"],
        sentiment_score=computed["components"]["sentiment_score"],
        risk_score=computed["components"]["risk_score"],
        regime_weight=computed["components"]["weights"]["regime"],
        flow_weight=computed["components"]["weights"]["flow"],
        sentiment_weight=computed["components"]["weights"]["sentiment"],
        risk_weight=computed["components"]["weights"]["risk"],
        composite_score=computed["composite_score"],
        label=computed["label"],
        confidence=computed["confidence"],
        generated_at=computed["generated_at"],
    )
    return computed


@router.get(
    "/{coingecko_id}/composite/interpretation",
    response_model=schemas.CompositeInterpretationResponse,
)
def read_composite_interpretation(
    coingecko_id: str,
    horizon_days: int = Query(default=30, ge=7, le=365),
    lower_threshold: float = Query(default=20.0, ge=0.0, le=100.0),
    upper_threshold: float = Query(default=60.0, ge=0.0, le=100.0),
    min_train_months: int = Query(default=12, ge=3, le=36),
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    if lower_threshold >= upper_threshold:
        raise HTTPException(status_code=400, detail="lower_threshold must be < upper_threshold")

    v1 = read_composite_score(coingecko_id=coingecko_id, db=db, _user=_user)
    v2 = read_composite_score_v2(coingecko_id=coingecko_id, horizon_days=horizon_days, db=db, _user=_user)
    crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")
    v2_history = crud.get_market_composite_v2_history(
        db=db,
        crypto_id=crypto.id,
        horizon_days=horizon_days,
        limit=8,
    )

    walk_forward = None
    try:
        walk_forward = read_composite_v2_walk_forward(
            coingecko_id=coingecko_id,
            horizon_days=horizon_days,
            min_train_months=min_train_months,
            lower_threshold=lower_threshold,
            upper_threshold=upper_threshold,
            limit=5000,
            db=db,
            _user=_user,
        )
    except HTTPException:
        walk_forward = None

    comp = v2["components"]
    regime_score = float(comp["regime_score"])
    flow_score = float(comp["flow_score"])
    risk_score = float(comp["risk_score"])
    sentiment_score = comp["sentiment_score"]
    flow_quality = str(comp["flow"]["quality"])
    sentiment_quality = str(comp["sentiment"]["quality"])

    reasons: list[str] = []
    if regime_score < 40:
        reasons.append(f"Regime estrutural fraco ({regime_score:.1f}) pressiona o contexto.")
    elif regime_score > 60:
        reasons.append(f"Regime estrutural favoravel ({regime_score:.1f}) sustenta contexto positivo.")
    else:
        reasons.append(f"Regime estrutural intermediario ({regime_score:.1f}) sem dominancia clara.")

    if flow_score < 45:
        reasons.append(f"Flow abaixo do neutro ({flow_score:.1f}) com qualidade {flow_quality}.")
    elif flow_score > 55:
        reasons.append(f"Flow acima do neutro ({flow_score:.1f}) com qualidade {flow_quality}.")
    else:
        reasons.append(f"Flow neutro ({flow_score:.1f}) com qualidade {flow_quality}.")

    if risk_score > 55:
        reasons.append(f"Risk elevado ({risk_score:.1f}) aumenta probabilidade de instabilidade.")
    elif risk_score < 35:
        reasons.append(f"Risk baixo ({risk_score:.1f}) reduz probabilidade de whipsaw.")
    else:
        reasons.append(f"Risk moderado ({risk_score:.1f}) exige disciplina de risco.")

    if sentiment_score is None:
        reasons.append(f"Sentimento indisponivel ({sentiment_quality}); peso redistribuido automaticamente.")
    else:
        reasons.append(f"Sentimento em {float(sentiment_score):.1f} ({sentiment_quality}).")

    reasons = reasons[:3]

    alerts: list[str] = []
    score_gap = float(v2["composite_score"]) - float(v1.composite_score)
    if abs(score_gap) >= 15:
        alerts.append(
            f"Divergencia relevante v1/v2: v1={float(v1.composite_score):.1f}, v2={float(v2['composite_score']):.1f}."
        )
    if flow_quality != "derivatives_plus_spot":
        alerts.append(f"Flow com fallback de qualidade ({flow_quality}).")
    if sentiment_quality != "external":
        alerts.append(f"Sentimento sem fonte externa completa ({sentiment_quality}).")

    if len(v2_history) >= 2:
        latest = float(v2_history[0].composite_score)
        prev = float(v2_history[1].composite_score)
        delta_1 = latest - prev
        if abs(delta_1) >= 8:
            alerts.append(f"Mudanca diaria forte no v2 ({delta_1:+.1f} pontos).")

    zone = _policy_zone(score=float(v2["composite_score"]), lower_threshold=lower_threshold, upper_threshold=upper_threshold)
    if zone == "risk_off":
        policy_implication = (
            f"Score v2 em zona risk-off (<= {lower_threshold:.0f}); leitura de defesa pela policy objetiva."
        )
    elif zone == "risk_on":
        policy_implication = (
            f"Score v2 em zona risk-on (>= {upper_threshold:.0f}); leitura de contexto construtivo pela policy objetiva."
        )
    else:
        policy_implication = (
            f"Score v2 em zona neutra ({lower_threshold:.0f}-{upper_threshold:.0f}); sem vantagem direcional forte."
        )

    if walk_forward is not None:
        if walk_forward.total_test_samples > 0:
            wf_hit = _format_pct((walk_forward.overall_hit_rate or 0) * 100)
            wf_sharpe = (
                f"{walk_forward.overall_sharpe:.3f}" if walk_forward.overall_sharpe is not None else "N/A"
            )
            wf_coverage = (walk_forward.total_active_signals / walk_forward.total_test_samples) * 100
            reliability = (
                f"Confianca interna {float(v2['confidence']) * 100:.1f}% | "
                f"WF {horizon_days}D hit-rate {wf_hit} sharpe {wf_sharpe} coverage {wf_coverage:.1f}%."
            )
        else:
            reliability = f"Confianca interna {float(v2['confidence']) * 100:.1f}% | walk-forward sem amostra ativa."
    else:
        reliability = f"Confianca interna {float(v2['confidence']) * 100:.1f}% | walk-forward indisponivel."

    summary = (
        f"{zone.replace('_', ' ').title()}: v2 {float(v2['composite_score']):.1f} ({v2['label']}) "
        f"vs v1 {float(v1.composite_score):.1f} ({v1.label})."
    )

    return schemas.CompositeInterpretationResponse(
        coingecko_id=coingecko_id,
        generated_at=datetime.now(UTC),
        horizon_days=horizon_days,
        lower_threshold=lower_threshold,
        upper_threshold=upper_threshold,
        v1_score=round(float(v1.composite_score), 4),
        v1_label=v1.label,
        v2_score=round(float(v2["composite_score"]), 4),
        v2_label=str(v2["label"]),
        summary=summary,
        reasons=reasons,
        reliability=reliability,
        policy_implication=policy_implication,
        alerts=alerts[:4],
        guardrails=[
            "Interpretacao de contexto; nao e recomendacao de compra/venda.",
            "Nao projeta preco futuro nem define tamanho de posicao.",
            "Qualquer decisao deve seguir policy objetiva e controle de risco.",
        ],
    )


@router.get("/{coingecko_id}/composite/v2/history", response_model=List[schemas.CompositeV2SnapshotResponse])
def read_composite_v2_history(
    coingecko_id: str,
    horizon_days: int = Query(default=30, ge=7, le=365),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = Query(default=365, ge=1, le=5000),
    db: Session = Depends(get_db),
    _user: str = Depends(require_auth),
):
    db_crypto = crud.get_cryptocurrency_by_coingecko_id(db, coingecko_id=coingecko_id)
    if db_crypto is None:
        raise HTTPException(status_code=404, detail="Cryptocurrency not found")

    rows = crud.get_market_composite_v2_history(
        db=db,
        crypto_id=db_crypto.id,
        horizon_days=horizon_days,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    output: list[schemas.CompositeV2SnapshotResponse] = []
    for row in reversed(rows):
        output.append(
            schemas.CompositeV2SnapshotResponse(
                snapshot_date=row.snapshot_date,
                horizon_days=row.horizon_days,
                regime_score=float(row.regime_score),
                flow_score=float(row.flow_score),
                sentiment_score=float(row.sentiment_score) if row.sentiment_score is not None else None,
                risk_score=float(row.risk_score),
                regime_weight=float(row.regime_weight),
                flow_weight=float(row.flow_weight),
                sentiment_weight=float(row.sentiment_weight),
                risk_weight=float(row.risk_weight),
                composite_score=float(row.composite_score),
                label=row.label,
                confidence=float(row.confidence),
                generated_at=row.generated_at,
            )
        )
    return output
