# The SignalPilot Origin Story

## "Who's watching the machines?"

It was 2:47 AM on a Tuesday in November when Maya Chen first said the words out loud.

She was sitting cross-legged on the floor of her apartment in San Francisco's Mission District, laptop balanced on a stack of old textbooks, surrounded by a graveyard of empty coffee cups. On her screen: a Slack thread from earlier that day where an AI agent at a Series C fintech company had run `DROP TABLE transactions` on a production database. No human in the loop. No audit trail. Twelve hours of customer payment data — gone.

"Who's watching the machines?" she muttered.

Her co-founder, James Okafor, heard her through the still-open video call they'd forgotten to hang up three hours ago. He was in his own apartment in Brooklyn, hunched over a terminal, tracing the aftermath of yet another AI-gone-wrong incident — this time a well-meaning LLM that had exfiltrated an entire customer table into a third-party API call because nobody had scoped its database permissions.

"Nobody," James said. "That's the problem."

---

## The Problem Nobody Was Solving

It was late 2024, and the world was racing to connect AI models to everything. Databases, APIs, internal tools — the promise of autonomous AI agents was intoxicating. Companies were handing GPT-4 and Claude the keys to their most sensitive datastores with little more than a system prompt and a prayer.

Maya had spent six years building data infrastructure at Stripe, where she'd learned that the boring work — access controls, audit logging, query validation — was the work that kept the company alive. James had been a security engineer at Datadog, where he'd watched the observability industry mature from "just log everything" to sophisticated, governed pipelines.

They'd met at a conference panel on AI safety, discovered they shared the same quiet horror at what they were seeing in the industry, and started talking every day.

The pattern was everywhere. Engineering teams were building incredible AI-powered workflows — natural language to SQL, automated reporting, intelligent dashboards — but the governance layer was an afterthought. Or worse, nonexistent. Every week brought a new horror story: data leaks, runaway queries that cratered production databases, SQL injection through prompt manipulation, AI agents accessing data they were never meant to see.

The existing solutions were blunt instruments. You could lock AI out of databases entirely (and lose all the value), or you could give it raw access and hope for the best. There was nothing in between — no intelligent middleware that understood both the promise and the peril.

"It's like we built commercial aviation," Maya told James one night, "but forgot to invent air traffic control."

---

## Three Weeks in a Garage (Well, a WeWork)

They quit their jobs on the same day in January 2025. Maya's manager at Stripe told her she was crazy. James's team at Datadog threw him a going-away party and told him they'd be his first customer.

They didn't have a fancy office. They had a two-person WeWork hot desk in SoMa, a whiteboard they'd bought from a closing Office Depot, and a single shared Figma board titled "THE PLAN" that was mostly arrows pointing at question marks.

The core insight was deceptively simple: AI models don't need raw database access. They need *governed* database access. A layer that sits between the model and the data, that understands SQL well enough to validate it, scope it, and audit it — in real time, at the speed AI demands.

James sketched the first architecture on the whiteboard in a single afternoon. A gateway server, built on FastAPI for speed. SQL parsing with SQLGlot so they could inspect and validate every query before it touched a database. Connection pooling with asyncpg because AI workloads were bursty and unpredictable. And an audit trail for everything — every query, every connection, every result.

Maya built the connector abstraction. She knew from Stripe that the database landscape was fragmented — Postgres today, Snowflake tomorrow, some proprietary data warehouse next quarter. The system needed to be pluggable. One clean interface, any backend.

They worked eighteen-hour days. James would code the gateway until his vision blurred, then hand off to Maya, who'd wire up the connectors and write validation logic until sunrise. They communicated in a shorthand that would have been unintelligible to anyone else — "the parser catches nested subqueries now" / "cool, I'll add the SSE stream for real-time metrics" / "we need sandboxing" / "I know, I'm looking at Firecracker."

The sandboxing was James's obsession. It wasn't enough to validate SQL. What if someone needed to run arbitrary code against query results — transformations, aggregations, custom logic? You couldn't just `exec()` that on your server. He spent a week getting Firecracker microvms working as an execution sandbox, lightweight enough to spin up in milliseconds, isolated enough that a rogue script couldn't touch anything it shouldn't.

---

## The Wall

Week four is when everything almost fell apart.

Maya had landed their first design partner — a mid-stage healthtech company called Vantage that was drowning in compliance requirements. Their head of data, a no-nonsense woman named Priya, agreed to a thirty-minute demo call. "Show me it works against our real query patterns," she said. "We'll send some examples ahead of time."

The examples arrived the night before: a stack of twelve SQL queries their analysts ran daily. Most were straightforward. Query number seven was not. It was a six-level nested CTE with window functions, lateral joins, and a recursive reference that calculated rolling patient cohort metrics. The kind of query that only exists in companies where analysts have been layering logic on logic for years.

Maya fed it into the gateway at 11 PM. SQLGlot choked. Not a graceful error — a hard crash, a stack trace, a silent exit code.

"James." She didn't need to say more. He was already looking at the same screen.

They spent the next four hours trying to patch the parser. Every fix broke something else. At 3 AM, James pushed back from his desk. "We can't ship this. The validation layer is the *whole product*. If it can't parse real-world SQL, we have nothing."

The demo was at 10 AM. They didn't sleep. By 6 AM, Maya had written a custom pre-processing step that decomposed complex CTEs into an intermediate representation before feeding them to SQLGlot. It was ugly. It was held together with duct tape. It worked.

Priya's query ran. Validated. Executed. Results streamed back clean. Priya nodded once and said, "Okay. I'm interested." She never knew how close it had been.

But the demo cracked open a deeper fault line. That weekend, James sat Maya down in the WeWork — which was empty on Saturdays, the fluorescent lights buzzing overhead — and told her they needed to stop building features and finish the Firecracker sandbox before talking to another customer.

"We're six weeks in and we don't have a single paying user," Maya shot back. "We can add sandboxing later. Right now we need to ship the gateway, get feedback, get *revenue* —"

"And when someone runs arbitrary Python through our system and it escapes into the host?" James's voice was steady but his jaw was tight. "When that happens — not if, *when* — we won't be the company that solves AI governance. We'll be the company that *proved it was impossible*. We'll be the next cautionary tale in someone else's Slack thread."

Maya stared at him. She wanted to argue. She had a spreadsheet on her laptop that showed their personal savings hitting zero in nine weeks. She'd done the math a dozen times, always hoping the numbers would change.

"If we ship insecure," James said, quieter now, "we *are* the problem we're solving."

The silence stretched. Maya closed the spreadsheet.

"Okay," she said. "Security first. Always."

It became the company's first principle, written on the whiteboard in James's handwriting and never erased: **Don't become the thing you're fighting.**

The next three weeks were brutal. They burned through savings faster than planned — AWS bills for Firecracker testing, the WeWork hot desk, the health insurance they were paying out of pocket. By week six, Maya had $4,200 left in her checking account. She opened LinkedIn one morning and stared at a recruiter message from her old team at Stripe. Senior Staff Engineer. The number had a lot of zeros.

She didn't tell James. She didn't need to. He'd seen her face when she checked her phone.

"I got one too," he said, not looking up from his terminal. "Datadog. Principal Security Architect."

"And?"

"And I keep thinking about Priya's face when that query came back clean. She's been fighting for governed data access at her company for two years and nobody would build it." He finally looked up. "If we go back, who builds this?"

Maya deleted the recruiter's message. Then she deleted the Stripe app from her phone for good measure.

"Nobody," she said. "That's the problem."

The same words from that first late night. But this time they weren't a complaint. They were a commitment.

---

## The Moment

It was a Friday evening, three weeks in. They were both running on caffeine and stubbornness. Maya had just finished wiring the MCP — Model Context Protocol — integration, which meant any AI model that spoke MCP could connect to their gateway natively. James had the audit logging pipeline streaming events in real time.

They decided to test it end-to-end.

Maya typed a natural language query into their bare-bones web UI: *"Show me all customers who signed up in the last 30 days and spent more than $500."*

The system parsed it. Validated the SQL. Checked it against the governance rules they'd configured — no access to the `passwords` column, no queries touching more than 10,000 rows without approval, no DDL statements ever. It routed the query through the connection pool, executed it against their test Postgres instance, and streamed the results back. The audit log captured everything: who asked, what was generated, what was executed, what was returned, and how long it took.

Total time: 340 milliseconds.

James leaned back in his chair. "Run it again," he said. "But try to break it."

Maya grinned. She tried SQL injection through the natural language input. Blocked. She tried a `DROP TABLE` hidden in a subquery. Caught and rejected. She tried accessing a column outside her permission scope. Denied, with a clean error message explaining why.

She tried crafting a prompt that would trick the AI into generating a query that *looked* innocent but would exfiltrate data through a side channel. The SQL parser caught the nested `COPY TO` buried three levels deep.

"It works," Maya said quietly.

"It works," James agreed.

They sat in silence for a moment, the weight of it settling in. They'd built something that didn't exist before — a governed bridge between AI and data. Not a wall. Not an open door. A *checkpoint* — intelligent, fast, and thorough.

James pulled up the real-time metrics dashboard. Query latency, active connections, governance violations caught, audit events per second — all streaming live. He turned his laptop to face Maya.

"We should call it SignalPilot," he said.

"Why?"

"Because that's what it does. It doesn't block the signal. It *pilots* it — makes sure it gets where it needs to go, safely."

Maya nodded slowly. "SignalPilot. I like it."

She opened a new file, typed `# SignalPilot` at the top, and started writing the README.

---

## What Came Next

Vantage went live on a Thursday in March.

Maya and James were sitting side by side at the WeWork — they'd upgraded to an actual office by then, a glass-walled room the size of a parking space with a door that stuck. James had the metrics dashboard on his laptop. Maya had the audit log stream on hers. Priya had texted twenty minutes ago: *"Deploying now. Fingers crossed."*

The first query hit the gateway at 2:14 PM Pacific. A simple `SELECT` — one of Vantage's analysts pulling a weekly patient enrollment summary through their AI copilot. The dashboard ticked: one active connection, one query validated, one result returned. Latency: 280 milliseconds.

Then the second query. Then a burst of six more. The SSE stream on Maya's screen started scrolling — real queries, real analysts, real patient data flowing through SignalPilot's governance layer. Every query parsed, validated against Vantage's HIPAA-scoped column policies, executed, logged. The numbers climbed. Ten queries. Fifty. Two hundred by end of day.

James didn't say anything. He just watched the dashboard. Active connections: 12. Governance checks passed: 847. Governance violations caught: 3. Three queries that would have touched columns containing protected health information outside the analyst's clearance level. Three quiet disasters that didn't happen.

Maya's phone buzzed at 11:47 PM that night. She was in bed, half asleep, laptop still warm on the nightstand. A Slack message from Priya:

> One of our AI agents tried to pull the full SSN column from the patients table tonight. Some prompt injection thing — the analyst didn't even realize the query had been manipulated. SignalPilot flagged it, blocked it, and logged the whole chain. Our compliance officer almost cried when I showed her the audit trail this morning. Nobody on the team even noticed it happened. It just worked.

Maya stared at the message for a long time. Then she screenshotted it and sent it to James with no caption.

He replied in four seconds: a photo of the whiteboard in their office. The one with his handwriting on it, the words they'd written during their worst week, the principle that had cost them three weeks of runway they couldn't afford.

*Don't become the thing you're fighting.*

Below it, in Maya's handwriting — added sometime that afternoon, while James wasn't looking — two new words:

*We didn't.*
