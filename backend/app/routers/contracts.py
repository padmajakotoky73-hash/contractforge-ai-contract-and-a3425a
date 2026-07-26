from __future__ import annotations

import io
import logging
import os
import urllib.request
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..config import settings
from ..services.entitlement import check_entitlement

router = APIRouter(prefix="/contracts", tags=["contracts"])
logger = logging.getLogger(__name__)

_INR = "₹"  # ₹

_GLM_MODEL = "z-ai/glm-5.2"
_GLM_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

# ── Font ──────────────────────────────────────────────────────────────────────

_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_FONT_INIT = False


def _init_font() -> None:
    global _FONT, _FONT_BOLD, _FONT_INIT
    if _FONT_INIT:
        return
    _FONT_INIT = True

    regular_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/ttf-dejavu/DejaVuSans.ttf",
    ]
    bold_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/ttf-dejavu/DejaVuSans-Bold.ttf",
    ]

    reg_path = next((p for p in regular_candidates if os.path.exists(p)), None)
    bold_path = next((p for p in bold_candidates if os.path.exists(p)), None)

    if not reg_path:
        base = "https://github.com/dejavu-fonts/dejavu-fonts/raw/version_2_37/ttf"
        for fname in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
            dest = f"/tmp/{fname}"
            if not os.path.exists(dest):
                try:
                    urllib.request.urlretrieve(f"{base}/{fname}", dest)
                except Exception:
                    pass
        reg_path = "/tmp/DejaVuSans.ttf" if os.path.exists("/tmp/DejaVuSans.ttf") else None
        bold_path = (
            "/tmp/DejaVuSans-Bold.ttf"
            if os.path.exists("/tmp/DejaVuSans-Bold.ttf")
            else None
        )

    if reg_path:
        pdfmetrics.registerFont(TTFont("DejaVuSans", reg_path))
        b = bold_path or reg_path
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", b))
        registerFontFamily("DejaVuSans", normal="DejaVuSans", bold="DejaVuSans-Bold")
        _FONT = "DejaVuSans"
        _FONT_BOLD = "DejaVuSans-Bold"


# ── Schemas ───────────────────────────────────────────────────────────────────


class ContractExportRequest(BaseModel):
    user_email: str = "anonymous@contractforge.io"
    freelancer_name: str = "Priya Sharma"
    freelancer_gst: str = "27AABCU9603R1ZX"
    freelancer_address: str = "Bandra West, Mumbai, Maharashtra 400050"
    client_name: str = "Rahul Sharma"
    client_company: str = "Sharma Enterprises Pvt Ltd"
    client_address: str = "Andheri East, Mumbai, Maharashtra 400069"
    deliverables: list[str] = [
        "Company website — 5 pages (Home, About, Services, Portfolio, Contact)",
        "Fully responsive design (mobile, tablet, desktop)",
        "CMS integration for content management",
        "SEO-optimized markup and meta tags",
        "Performance-optimized asset pipeline",
    ]
    timeline: str = "30 days from agreement date"
    amount: int = 75000
    payment_schedule: str = (
        "₹37,500 advance on signing; ₹37,500 on final delivery"
    )


_JURISDICTION_CLAUSES: dict[str, str] = {
    "India": (
        "This Agreement is governed by the laws of India. Disputes shall be subject to exclusive "
        "jurisdiction of competent courts in Mumbai, Maharashtra, with mandatory pre-litigation "
        "arbitration under the Arbitration and Conciliation Act, 1996."
    ),
    "UK": (
        "This Agreement is governed by the laws of England and Wales. The Contracts (Rights of "
        "Third Parties) Act 1999 applies. IR35 status determination obligations are acknowledged. "
        "Disputes shall be resolved in courts of England and Wales."
    ),
    "US": (
        "This Agreement is governed by the laws of the State of [State], without regard to "
        "conflict of law provisions. All intellectual property and work product created under "
        "this Agreement are assigned to the Client upon full payment, unless otherwise agreed in writing."
    ),
}

class ContractGenerateRequest(BaseModel):
    user_email: str = "anonymous@contractforge.io"
    project_type: str
    client_name: str
    client_company: str
    scope: str
    fee: int
    currency: str = "INR"
    payment_terms: str
    timeline: str
    jurisdiction: str = "India"


class ContractGenerateResponse(BaseModel):
    id: str
    content: str
    created_at: str


# ── PDF builder ───────────────────────────────────────────────────────────────


def _build_pdf(contract_id: str, req: ContractExportRequest) -> bytes:
    _init_font()

    buf = io.BytesIO()
    page_w, _ = A4
    margin = 2.5 * cm
    avail_w = page_w - 2 * margin

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=margin,
        leftMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
    )

    h1 = ParagraphStyle(
        "h1", fontName=_FONT_BOLD, fontSize=18, alignment=TA_CENTER, spaceAfter=4
    )
    right_style = ParagraphStyle(
        "right_style", fontName=_FONT, fontSize=9, alignment=TA_RIGHT, spaceAfter=2
    )
    sec = ParagraphStyle(
        "sec", fontName=_FONT_BOLD, fontSize=11, spaceBefore=14, spaceAfter=6
    )
    body = ParagraphStyle("body", fontName=_FONT, fontSize=10, leading=14, spaceAfter=4)
    bold_body = ParagraphStyle(
        "bold_body", fontName=_FONT_BOLD, fontSize=10, leading=14, spaceAfter=4
    )
    sig_hdr = ParagraphStyle(
        "sig_hdr", fontName=_FONT_BOLD, fontSize=10, spaceAfter=4
    )
    sig_row = ParagraphStyle("sig_row", fontName=_FONT, fontSize=9, spaceAfter=10)

    today = datetime.utcnow().strftime("%d %B %Y")
    inr = f"{_INR}{req.amount:,}"
    blank = "_____________________________"

    story: list = []

    # 1 — HEADER
    story.append(Paragraph("SERVICE AGREEMENT", h1))
    story.append(Paragraph(f"Contract ID: {contract_id}", right_style))
    story.append(Paragraph(f"Date: {today}", right_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.black))
    story.append(Spacer(1, 0.3 * cm))

    # 2 — PARTIES
    story.append(Paragraph("1. PARTIES", sec))
    story.append(Paragraph("This Agreement is entered into between:", body))
    story.append(Spacer(1, 0.15 * cm))
    story.append(Paragraph("FREELANCER", bold_body))
    story.append(Paragraph(f"Name: {req.freelancer_name}", body))
    story.append(Paragraph(f"GST Registration No.: {req.freelancer_gst}", body))
    story.append(Paragraph(f"Address: {req.freelancer_address}", body))
    story.append(Spacer(1, 0.15 * cm))
    story.append(Paragraph("CLIENT", bold_body))
    story.append(Paragraph(f"Name: {req.client_name}", body))
    story.append(Paragraph(f"Company: {req.client_company}", body))
    story.append(Paragraph(f"Address: {req.client_address}", body))

    # 3 — SCOPE OF WORK
    story.append(Paragraph("2. SCOPE OF WORK", sec))
    story.append(Paragraph("The Freelancer agrees to deliver the following:", body))
    for i, d in enumerate(req.deliverables, 1):
        story.append(Paragraph(f"  {i}. {d}", body))
    story.append(Spacer(1, 0.1 * cm))
    story.append(Paragraph(f"Timeline / Delivery Date: {req.timeline}", bold_body))

    # 4 — PAYMENT TERMS
    story.append(Paragraph("3. PAYMENT TERMS", sec))
    story.append(Paragraph(f"Total Project Fee: {inr} (Indian Rupees)", bold_body))
    story.append(Paragraph(f"Payment Schedule: {req.payment_schedule}", body))
    story.append(Spacer(1, 0.1 * cm))
    story.append(
        Paragraph(
            "GST at 18% shall be applicable in addition to the fees stated above. "
            "The Freelancer shall issue a valid GST invoice upon receipt of each payment.",
            body,
        )
    )
    story.append(Spacer(1, 0.1 * cm))
    story.append(
        Paragraph(
            "Interest on delayed payments: 18% per annum shall be charged on all outstanding "
            "amounts, as provided under the Indian Contract Act, 1872 (Sections 73–74).",
            body,
        )
    )

    # 5 — JURISDICTION
    story.append(Paragraph("4. GOVERNING LAW AND JURISDICTION", sec))
    story.append(
        Paragraph(
            "This Agreement is governed by and construed in accordance with the laws of India. "
            "Any disputes arising out of or in connection with this Agreement shall be subject to "
            "the exclusive jurisdiction of the competent courts in Mumbai, Maharashtra.",
            body,
        )
    )

    # 6 — TERMINATION
    story.append(Paragraph("5. TERMINATION", sec))
    story.append(
        Paragraph(
            "Either party may terminate this Agreement by providing 15 (fifteen) days' written "
            "notice to the other party. Upon termination, the Client shall pay the Freelancer for "
            "all work completed and deliverables provided up to the termination date.",
            body,
        )
    )

    # 7 — CONFIDENTIALITY
    story.append(Paragraph("6. CONFIDENTIALITY", sec))
    story.append(
        Paragraph(
            "Each party shall keep confidential all proprietary information, trade secrets, "
            "business data, and intellectual property disclosed by the other party. This obligation "
            "survives termination and remains in effect for two (2) years from the date of "
            "termination or expiry of this Agreement.",
            body,
        )
    )

    # 8 — ENTIRE AGREEMENT
    story.append(Paragraph("7. ENTIRE AGREEMENT", sec))
    story.append(
        Paragraph(
            "This Agreement constitutes the entire agreement between the parties with respect to "
            "its subject matter and supersedes all prior negotiations, representations, warranties, "
            "and understandings of the parties with respect thereto. No modification or amendment "
            "of this Agreement shall be effective unless made in writing and signed by authorised "
            "representatives of both parties.",
            body,
        )
    )

    # 9 — SIGNATURE BLOCK (two-column)
    story.append(Paragraph("8. SIGNATURES", sec))
    story.append(
        Paragraph(
            "By signing below, both parties confirm they have read, understood, and agreed to "
            "the terms of this Agreement.",
            body,
        )
    )
    story.append(Spacer(1, 0.4 * cm))

    col = avail_w / 2
    sig_table = Table(
        [
            [
                [
                    Paragraph("FREELANCER", sig_hdr),
                    Paragraph(f"Name: {req.freelancer_name}", sig_row),
                    Paragraph(f"Designation: {blank}", sig_row),
                    Spacer(1, 0.6 * cm),
                    Paragraph(f"Signature: {blank}", sig_row),
                    Paragraph(f"Date: {blank}", sig_row),
                    Paragraph(f"Place: {blank}", sig_row),
                ],
                [
                    Paragraph("CLIENT", sig_hdr),
                    Paragraph(f"Name: {req.client_name}", sig_row),
                    Paragraph(f"Company: {req.client_company}", sig_row),
                    Spacer(1, 0.6 * cm),
                    Paragraph(f"Signature: {blank}", sig_row),
                    Paragraph(f"Date: {blank}", sig_row),
                    Paragraph(f"Place: {blank}", sig_row),
                ],
            ]
        ],
        colWidths=[col, col],
    )
    sig_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("LINEAFTER", (0, 0), (0, -1), 0.5, colors.grey),
            ]
        )
    )
    story.append(sig_table)

    doc.build(story)
    return buf.getvalue()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _paywall_detail(reason: str) -> dict:
    return {
        "error": "subscription_required",
        "upgrade_url": "/pricing",
        "checkout_monthly": settings.lemonsqueezy_checkout_monthly,
        "checkout_per_contract": settings.lemonsqueezy_checkout_per_contract,
        "message": "Generate unlimited contracts from ₹2,499/month",
    }


def _call_glm(system_prompt: str, user_prompt: str) -> str:
    """Call GLM-5.2 via OpenRouter. Raises on auth/rate-limit/network/malformed-response
    failures so the caller can fall back to Claude."""
    resp = httpx.post(
        _GLM_ENDPOINT,
        headers={
            "Authorization": f"Bearer {settings.glm_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": _GLM_MODEL,
            "max_tokens": 4096,
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/{contract_id}/export")
async def export_contract(
    contract_id: str,
    request: Request,
    payload: Optional[ContractExportRequest] = None,
) -> StreamingResponse:
    req = payload or ContractExportRequest()
    supabase = getattr(request.app.state, "supabase", None)
    allowed, reason = await check_entitlement(req.user_email, supabase, consume=False)
    if not allowed:
        raise HTTPException(status_code=402, detail=_paywall_detail(reason))

    pdf_bytes = _build_pdf(contract_id, req)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="contract_{contract_id}.pdf"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


@router.post("/generate", response_model=ContractGenerateResponse)
async def generate_contract(
    payload: ContractGenerateRequest,
    request: Request,
) -> ContractGenerateResponse:
    import anthropic as _anthropic

    supabase = getattr(request.app.state, "supabase", None)
    allowed, reason = await check_entitlement(payload.user_email, supabase, consume=True)
    if not allowed:
        raise HTTPException(status_code=402, detail=_paywall_detail(reason))

    jurisdiction_clause = _JURISDICTION_CLAUSES.get(
        payload.jurisdiction, _JURISDICTION_CLAUSES["India"]
    )
    india_extras = (
        f"- GST clause: 18% applicable, freelancer issues GST invoice\n"
        f"- All monetary amounts in INR using {_INR} symbol\n"
        f"- Late payment: 18% per annum (Indian Contract Act, 1872, Sections 73-74)\n"
    ) if payload.jurisdiction == "India" else ""
    system_prompt = (
        f"You are a legal contract drafting assistant generating professional, legally sound "
        f"service agreements governed by {payload.jurisdiction} law.\n\n"
        "Always include without exception:\n"
        + india_extras
        + f"- Governing law: {jurisdiction_clause}\n\n"
        "Generate complete clauses. No placeholder text. No [INSERT], no TBD, no blanks."
    )

    user_prompt = (
        f"Draft a concise service agreement (MAXIMUM 1000 words). Each clause: 2–4 sentences.\n\n"
        f"Project Type: {payload.project_type}\n"
        f"Client Name: {payload.client_name}\n"
        f"Client Company: {payload.client_company}\n"
        f"Scope: {payload.scope}\n"
        f"Fee: {_INR}{payload.fee:,} (Indian Rupees)\n"
        f"Payment Terms: {payload.payment_terms}\n"
        f"Timeline: {payload.timeline}\n\n"
        f"CONTRACT STRUCTURE — use exactly these 8 sections in order:\n"
        f"1. PARTIES — name both parties\n"
        f"2. SCOPE OF WORK — deliverables and timeline\n"
        f"3. PAYMENT TERMS — must include: {_INR}{payload.fee:,} | "
        f"GST at 18% shall be applicable. The Freelancer shall issue a valid GST invoice. | "
        f"Interest at the rate of 18% per annum on outstanding amounts, "
        f"per Indian Contract Act, 1872 (Sections 73–74).\n"
        f"4. GOVERNING LAW — must include: This Agreement is governed by the laws of India. "
        f"Disputes shall be subject to exclusive jurisdiction of courts in Mumbai, Maharashtra.\n"
        f"5. TERMINATION — 15 days written notice\n"
        f"6. CONFIDENTIALITY — 2 years post-agreement\n"
        f"7. ENTIRE AGREEMENT — standard boilerplate\n"
        f"8. SIGNATURES — two-column: Service Provider | {payload.client_name}\n\n"
        f"Use '{payload.client_name}' / '{payload.client_company}' for client, "
        f"'Service Provider' for freelancer. No brackets, no placeholders."
    )

    content: Optional[str] = None

    if settings.glm_api_key:
        try:
            content = _call_glm(system_prompt, user_prompt)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as e:
            logger.warning("GLM-5.2 generation failed, falling back to Claude: %s", e)

    if content is None:
        if not settings.anthropic_api_key:
            raise HTTPException(
                status_code=503, detail="ANTHROPIC_API_KEY not configured on server"
            )

        client = _anthropic.Anthropic(api_key=settings.anthropic_api_key)

        try:
            message = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                temperature=0.3,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except _anthropic.AuthenticationError as e:
            raise HTTPException(status_code=401, detail=f"Anthropic auth failed: {e}")
        except _anthropic.APIError as e:
            raise HTTPException(status_code=502, detail=f"Anthropic API error: {e}")

        content = message.content[0].text

    contract_id = f"cf-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    return ContractGenerateResponse(
        id=contract_id,
        content=content,
        created_at=datetime.utcnow().isoformat(),
    )
