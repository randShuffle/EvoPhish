import os
import json
import re
import time
import base64
from typing import List, Optional, Dict, Any

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# ============================================================
# Pydantic Models
# ============================================================


class ReferenceLogo(BaseModel):
    brand: str = Field(..., description="Brand name of the reference logo")
    logo_path: str = Field(
        ..., description="File path to the reference logo image (absolute or relative to CWD)"
    )


class MatchRequest(BaseModel):
    target_logo_path: str = Field(
        ..., description="File path to the cropped target logo image (absolute or relative to CWD)"
    )
    reference_logos: List[ReferenceLogo] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="List of reference logos (1–10) to match against",
    )


class MatchResponse(BaseModel):
    matched_brand: Optional[str] = Field(
        None, description="Matched brand name if a match was found, or null"
    )
    reason: Optional[str] = Field(None, description="VLM's reasoning for the match decision")
    success: bool = Field(True, description="Whether inference completed successfully")


class HealthResponse(BaseModel):
    status: str
    vllm_connected: bool
    vllm_url: str


# ============================================================
# Image Utility
# ============================================================


def load_image_base64(path: str) -> str:
    """
    Read an image file from disk and return its base64-encoded content.

    Args:
        path: Absolute or relative file path to the image.

    Returns:
        Raw base64 string (no data URI prefix).
    """
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


class ReferenceLogo:
    brand: str

def build_vlm_prompt(candidates: List[ReferenceLogo]) -> str:
    """Build the VLM prompt exactly as in benchmark/stage3_rerank.py."""
    total = len(candidates)
    valid_brands = sorted(set(c.brand for c in candidates))

    prompt = f"""You are a professional logo brand identity matching expert with zero tolerance for ambiguity.

Task: Determine which brand the query logo belongs to by comparing brand identity with the {total} reference logos below.

STRICT, NON-NEGOTIABLE RULES:
1. VALID BRANDS ONLY: The query logo can ONLY match one brand from this list: [{', '.join(valid_brands)}], or NO MATCH.
2. MATCH DEFINITION: First, extract and summarize the complete brand identity from all visual dimensions of the query logo (including logo design, graphic symbol, core visual elements, text trademark, unique brand features); then strictly match this summarized brand identity against the reference logos. A valid match is confirmed ONLY when the full brand identity is fully consistent with one reference.
3. OUTPUT NULL IN ALL THESE CASES:
   - Uncertain / doubtful match
   - Similar but not identical brand identity
   - No matching brand identity in references
   - Any ambiguity or inconsistency
4. FORBIDDEN: Output any brand name NOT in the valid list above.
5. FORBIDDEN: Output any extra text, explanation, or comment.

REQUIRED OUTPUT: ONLY a JSON object, NOTHING ELSE:
{{"brand": "exact_brand_name"}}  (when brand identity is a definite, full match)
{{"brand": null}}                (all other cases)

Examples:
{{"brand": "Google"}}
{{"brand": null}}"""
    return prompt



def parse_vlm_response(response: str) -> Optional[str]:
    """Parse VLM response and return the brand string, or None.

    Mirrors benchmark/stage3_rerank.py: extracts {"brand": "name"} or {"brand": null}.
    """
    json_match = re.search(r"\{[^}]+\}", response, re.DOTALL)
    if json_match:
        try:
            result = json.loads(json_match.group())
            return result.get("brand")
        except (json.JSONDecodeError, AttributeError):
            pass
    return None


# ============================================================
# vLLM HTTP Client (OpenAI-compatible)
# ============================================================


class VLLMHttpClient:
    """
    Lightweight client for vLLM's OpenAI-compatible chat completions API.

    Sends multimodal messages (text + image_url with base64 data) directly to
    the vLLM HTTP server without needing the transformers/vllm Python packages
    in the service process.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:7000/v1",
        model: Optional[str] = None,
        timeout: int = 120,
        max_retries: int = 2,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    def _build_messages(
        self,
        prompt: str,
        target_logo_path: str,
        reference_logos: List[ReferenceLogo],
    ) -> List[Dict]:
        """
        Build OpenAI-compatible multimodal messages.

        Reads images from disk paths and embeds them as base64 data URIs
        for the vLLM HTTP API.  This follows the same pattern as
        benchmark/stage3_rerank.py which passes image file paths directly
        to the Qwen processor.
        """
        content: List[Dict] = [{"type": "text", "text": prompt}]

        # Add target logo (the unknown logo to match)
        target_b64 = load_image_base64(target_logo_path)
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{target_b64}"},
            }
        )

        # Add each reference logo with its brand label
        for i, ref in enumerate(reference_logos):
            ref_b64 = load_image_base64(ref.logo_path)
            content.append(
                {"type": "text", "text": f"Reference logo {i+1}: {ref.brand}"}
            )
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{ref_b64}"},
                }
            )

        return [{"role": "user", "content": content}]

    def chat_completions_create(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> Dict[str, Any]:
        """
        Send a chat completion request to the vLLM HTTP server.

        Uses exponential backoff retry on transient failures.
        """
        payload: Dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # Only include model if explicitly set (some vLLM setups serve one model)
        if self.model:
            payload["model"] = self.model

        last_error = None
        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    time.sleep(1.5**attempt)

        raise ConnectionError(
            f"vLLM request failed after {self.max_retries} attempts: {last_error}"
        )

    def health_check(self) -> bool:
        """Check if the vLLM server is reachable via its /health or /models endpoint."""
        # Try the vLLM /health endpoint first
        base = self.base_url.replace("/v1", "").replace("/v1/", "")
        try:
            resp = requests.get(f"{base}/health", timeout=5)
            if resp.status_code == 200:
                return True
        except Exception:
            pass

        # Fallback: query /v1/models
        try:
            resp = requests.get(f"{self.base_url}/models", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False


# ============================================================
# FastAPI Application
# ============================================================

app = FastAPI(
    title="Logo Brand Matching Service",
    description=(
        "VLM-powered logo-to-reference brand identity matching. "
        "Accepts a target logo (base64) and reference logos (base64 + brand name), "
        "then uses vLLM-hosted Qwen3-VL to determine the best match."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global vLLM client (initialized at startup)
vllm_client: Optional[VLLMHttpClient] = None


@app.on_event("startup")
async def startup():
    """Initialize the vLLM HTTP client from environment variables."""
    global vllm_client

    vllm_url = os.environ.get(
        "VLLM_URL", "http://localhost:7000/v1"
    )
    vllm_model = os.environ.get("VLLM_MODEL")

    vllm_client = VLLMHttpClient(
        base_url=vllm_url,
        model=vllm_model,
    )

    if vllm_client.health_check():
        print(f"[INFO] Connected to vLLM server at {vllm_url}")
        if vllm_model:
            print(f"[INFO] Using model: {vllm_model}")
    else:
        print(
            f"[WARN] vLLM server at {vllm_url} is not reachable. "
            f"The service will start but /match will fail until vLLM is available."
        )


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check — reports service status and vLLM connectivity."""
    connected = vllm_client.health_check() if vllm_client else False
    return HealthResponse(
        status="ok" if connected else "degraded",
        vllm_connected=connected,
        vllm_url=vllm_client.base_url if vllm_client else "not configured",
    )


@app.post("/match", response_model=MatchResponse)
async def match_logo(request: MatchRequest):
    """
    Match a target logo against a list of reference logos.

    The VLM analyzes the target logo and compares it with each reference,
    returning which reference it matches (or "no match").
    """
    global vllm_client

    if vllm_client is None:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # --- input validation ---
    if not request.target_logo_path.strip():
        raise HTTPException(status_code=400, detail="target_logo_path is required")
    if not os.path.exists(request.target_logo_path):
        raise HTTPException(
            status_code=400,
            detail=f"target_logo_path not found: {request.target_logo_path}",
        )

    num_refs = len(request.reference_logos)
    if num_refs < 1:
        raise HTTPException(
            status_code=400, detail="At least 1 reference logo is required"
        )

    # Validate all reference logo paths exist
    for i, ref in enumerate(request.reference_logos):
        if not ref.logo_path.strip():
            raise HTTPException(
                status_code=400,
                detail=f"reference_logos[{i}].logo_path is required",
            )
        if not os.path.exists(ref.logo_path):
            raise HTTPException(
                status_code=400,
                detail=f"reference_logos[{i}].logo_path not found: {ref.logo_path}",
            )

    # --- build prompt ---
    prompt = build_vlm_prompt(request.reference_logos)

    # --- build multimodal messages (reads images from disk paths) ---
    messages = vllm_client._build_messages(
        prompt=prompt,
        target_logo_path=request.target_logo_path,
        reference_logos=request.reference_logos,
    )

    # --- call vLLM ---
    try:
        response = vllm_client.chat_completions_create(messages)
        choices = response.get("choices", [])
        if not choices:
            return MatchResponse(
                matched_brand=None,
                reason="vLLM returned empty choices",
                success=False,
            )
        raw_text = choices[0].get("message", {}).get("content", "")
    except Exception as e:
        return MatchResponse(
            matched_brand=None,
            reason=f"Inference failed: {e}",
            success=False,
        )

    # --- parse result (mirrors benchmark: parse brand string) ---
    vlm_brand = parse_vlm_response(raw_text)

    # --- validate and return ---
    candidate_brands = {ref.brand for ref in request.reference_logos}

    if vlm_brand is not None and vlm_brand in candidate_brands:
        return MatchResponse(
            matched_brand=vlm_brand,
            reason=f"Brand identity matches {vlm_brand}",
            success=True,
        )

    return MatchResponse(
        matched_brand=None,
        reason=f"{'Failed to parse VLM response' if vlm_brand is None else f'None of the reference logos match (VLM output: {vlm_brand})'}",
        success=True,
    )


@app.get("/models")
async def list_models():
    """Proxy to vLLM's /v1/models endpoint — lists available models."""
    if vllm_client is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    try:
        resp = requests.get(f"{vllm_client.base_url}/models", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=str(e))


# ============================================================
# Entry Point
# ============================================================


def main():
    parser = __import__("argparse").ArgumentParser(
        description="Stage 3 Reranking Service — Logo Brand Identity Matching via vLLM"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Service bind host (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7077,
        help="Service bind port (default: 7077)",
    )
    parser.add_argument(
        "--vllm-url",
        type=str,
        default="http://localhost:7000/v1",
        help="vLLM HTTP server URL, e.g. http://host:7000/v1 (default: http://localhost:7000/v1)",
    )
    parser.add_argument(
        "--vllm-model",
        type=str,
        default=None,
        help="Model name on the vLLM server (optional, auto-detected if omitted)",
    )

    args = parser.parse_args()

    # Pass config to the FastAPI app via env vars
    os.environ["VLLM_URL"] = args.vllm_url
    if args.vllm_model:
        os.environ["VLLM_MODEL"] = args.vllm_model

    print(f"[INFO] Starting Logo Matching Service on {args.host}:{args.port}")
    print(f"[INFO] vLLM endpoint: {args.vllm_url}")
    if args.vllm_model:
        print(f"[INFO] Model: {args.vllm_model}")
    print()

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
