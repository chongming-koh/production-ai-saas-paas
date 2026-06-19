# Janus

A conversational AI digital twin deployed to AWS. FastAPI + OpenAI backend on
Lambda (behind API Gateway), Next.js static frontend on S3 served via CloudFront.

Architecture: `CloudFront -> S3 (frontend) | API Gateway -> Lambda -> LLM / S3 (memory)`

---

## The Five AWS Components

| Service | What it is | Role in Janus |
|---|---|---|
| **S3** (Simple Storage Service) | A cloud shared drive, organized into **buckets** (dirs + files) | Two buckets: `memory` (conversations) and `frontend` (static site) |
| **Lambda** | Individual functions run on the cloud; pay only for CPU cycles used | Holds the digital twin business logic |
| **CloudFront** | Amazon's **CDN** - pushes static assets to edge data centers worldwide so users load them from a location near them | Serves the static frontend globally (a "distribution") |
| **API Gateway** | Manages the external APIs you expose (rate limiting, scaling, instrumentation) in front of Lambda | The front door to the backend; best practice vs exposing Lambda directly |
| **Bedrock** | Amazon's service for calling frontier foundation LLMs (plus an agent platform) | The AI layer that generates the twin's replies |

**Naming note:** "Amazon X" = early or consumer-facing products (Amazon S3, Amazon
Bedrock); "AWS X" = engineer-facing (AWS Lambda). Match whatever the docs use.

## Deployment Architecture (Digital Twin Mk2)

**Backend:** API Gateway -> Lambda (business logic) -> reads/writes the S3 `memory`
bucket and calls the LLM. Each user conversation is a separate file in `memory`,
because every LLM call is **stateless** - the full conversation must be re-sent
each time, so it has to be stored between requests.

**Frontend:** Next.js static export (HTML/JS/CSS) -> S3 `frontend` bucket ->
CloudFront distribution (global delivery).

**Where they meet: the browser.** The user opens the CloudFront URL, the browser
renders the static site, and typing a message fires an API call to API Gateway ->
Lambda -> LLM + S3 memory. The frontend and backend are otherwise fully separate.

> Note: the course's target architecture uses **Bedrock** as the LLM. The Day 2
> build of Janus actually wires up **OpenAI (gpt-4o-mini)**; the switch to Bedrock
> comes later (Day 3/4, where Terraform sets a `bedrock_model_id`). Same
> architecture, swappable LLM layer.

---

## Troubleshooting Log

A running record of problems hit during deployment and how they were solved.
Kept as a learning log for my platform engineering journey.

### 2026-06-19 - Chat returns "Sorry, I encountered an error"

**Symptom:** Frontend loaded over CloudFront, but every message failed. The
browser failed in ~4s while showing a generic error.

**False leads:** Looked like CORS. Couldn't find CloudWatch logs (cause: console
was in the wrong region - Lambda is in `ap-southeast-1`, not `us-east-1`).

**Isolating the backend:** Tested the Lambda directly with a `POST /chat` test
event in the console. It returned `statusCode 200` with a real reply in 21s - so
OpenAI and the S3 memory write both worked. The backend was fine.

**Root cause:** The browser Network tab showed the only request was to `/health`
(405), never `/chat`. But the current `twin.tsx` only calls `POST /chat`. The
live header also said "AI Janus" while the source said "AI Digital Twin".
CloudFront was serving a **stale JavaScript bundle** built from older code. Every
backend "fix" had no effect because the live frontend never sent a chat request.

**Fix:** Rebuild the frontend and bust both caches (S3 and CloudFront):

```bash
cd frontend
npm run build
aws s3 sync out/ s3://twin-frontend-570/ --delete
aws cloudfront create-invalidation --distribution-id YOUR-DIST-ID --paths "/*"
# then Ctrl+Shift+R to bypass the browser cache
```

**Lessons:**
- A "fix" with no effect means you are fixing the wrong layer. Confirm *which
  request actually fires* (Network tab), not just that an error exists.
- Isolate layers: a Lambda test event proved the backend worked and redirected
  all suspicion to the frontend delivery path.
- A deployed static frontend is cached at three levels: S3 (`sync --delete`),
  CloudFront (invalidation), and the browser (Ctrl+Shift+R). Editing source is
  not enough.
- AWS consoles are region-scoped. "No log group" was just the wrong region.

---

## Concepts Learned

### Two ways to run an app on AWS: App Runner vs Lambda

The course taught both. They are substitutable ways to host the same backend -
pick by traffic pattern and cost.

| | App Runner (Week 1) | Lambda (Week 2 / Janus) |
|---|---|---|
| Compute | Container, **always running** (min 1 instance) | Function, **runs only per request** |
| Packaging | Next.js + FastAPI in **one container** -> ECR | FastAPI wrapped with **Mangum** -> zip |
| Frontend | Served **by the same container** | **Separate**: S3 + CloudFront |
| Routing | App Runner URL directly | API Gateway -> Lambda |
| Cost | ~$5-6/month, paid even when idle | Pay-per-request, ~free at low traffic |
| Cold starts | None (always warm) | Yes (first request after idle is slower) |

- **App Runner** = always-on server in a box. Simple, steady latency, but you pay
  24/7. Good for steady traffic.
- **Lambda** = wakes on demand, scales to zero, near-free for a personal project.
  Trade-offs: cold starts, an execution time limit (Janus uses a 30s timeout),
  and the frontend must be hosted separately (S3 + CloudFront).
- The frontend split is the key difference. Lambda's separate CloudFront layer is
  exactly what made the stale-cache bug above possible; App Runner serves the
  frontend from the container, so it has no separate CDN cache to invalidate.

**The real difference is the compute model, not the packaging format.** It is
tempting to think "App Runner = image, Lambda = zip," but that is an
oversimplification: Lambda can *also* be deployed as a container image (up to
10 GB), not only a zip. So packaging is a detail, not the distinction. The true
difference is:

- **App Runner** = a container that **stays running** (always-on, pay continuously,
  no cold starts). Container image only.
- **Lambda** = a function that **runs per request, then stops** (scale-to-zero,
  pay-per-use, cold starts). Packaged as zip **or** container image.

You don't pick Lambda because it uses a zip; you pick it for pay-per-use,
scale-to-zero compute. The zip is just the simplest way to get code onto Lambda -
and in this course Docker only *builds* that zip for Linux, it does not deploy it.

### Lambda packaging: zip vs container image - when to choose

For Lambda specifically (it accepts both), the deciding factor is usually size.

| | Zip | Container image |
|---|---|---|
| Size limit | 250 MB unzipped | **10 GB** |
| Registry | None - just upload | Must push to ECR |
| Cold start | Faster for small packages | Heavier; large images cold-start slower |
| Workflow | Simplest | More steps (build, tag, push, ECR) |

**Choose zip when** (the default, and what Janus uses):
- Dependencies fit under 250 MB unzipped
- A standard managed runtime (Python 3.12, etc.) is enough
- You want the simplest pipeline and fastest cold starts
- Packages are pure Python or have prebuilt Linux wheels (manylinux)

**Choose a container image when:**
- You exceed 250 MB (the #1 reason - e.g. heavy ML stacks like PyTorch/TensorFlow)
- You need system binaries not in the Lambda runtime (ffmpeg, custom C libs, fonts)
- You already containerize everything and want one consistent build/CI workflow
- You need precise control over the OS/runtime

**Rule of thumb:** start with zip (simpler, faster cold starts); switch to a
container image only when something forces you to - almost always size (>250 MB)
or a system dependency you can't fit in a zip. Janus stays on zip because its
manylinux wheels keep it small; a heavy ML model or binary tool would be the
trigger to flip to the image path.

### Docker: "build" vs "run" - same tool, two roles

Docker appears in both weeks but does something completely different each time.

- **Week 1 (App Runner): Docker *runs* the app.** Build an image, push to ECR,
  App Runner keeps that container running as the live backend. The container *is*
  production.
- **Week 2 Day 2 (Lambda): Docker only *builds* the package.** `deploy.py` runs
  `docker run --rm ... public.ecr.aws/lambda/python:3.12` just to `pip install`
  dependencies, then `--rm` throws the container away. The output is a zip; no
  container runs in production.

**Why use a throwaway Docker container to pip install?** Platform mismatch. This
machine is Windows; Lambda runs Amazon Linux x86_64. Installing directly on
Windows produces Windows-compiled binaries that crash on Lambda. The official AWS
Lambda image is a clean Linux build environment that guarantees the dependencies
match Lambda's runtime. Build, extract, discard.
