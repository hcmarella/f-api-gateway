# Glossary

**Triage**: the first node in the agent graph, a lightweight classifier that
decides which downstream branch (skill_match, rag_node, live_data_node,
etc.) is most likely to answer the user's question.

**Skill**: a small, structured `.md` file under `knowledge/skills/` with
frontmatter describing an id, name, description, allowed personas, triggers,
and an action or MCP tool to invoke. Skills represent known, well-defined
tasks the assistant can perform, as opposed to open-ended RAG lookups.

**RAG node**: the graph node responsible for embedding the user's question,
searching `knowledge_chunks` via cosine similarity, and returning the
top-matching chunks as candidate context.

**Live data node**: the graph node responsible for calling out to a live
external system (Jira, SharePoint) at query time rather than retrieving from
a pre-indexed knowledge base, used when the answer depends on current state
rather than static documentation.

**Draft skill**: a fallback node that fires only when triage, skill_match,
and rag_node all fail to confidently match a question. It logs the gap and
stages a proposed new skill in the review queue rather than answering
directly or writing to the knowledge base.

**Gates**: the node that applies policy checks (persona access, confidence
thresholds) to a candidate answer before it's returned to the user.

**Eval score**: the node that scores a completed answer for quality, used to
populate `eval_case_log` and to compare retrieval engines (see the graph
database comparison harness under `test/`).

**Persona**: one of `business`, `developer`, or `admin`, assigned per user,
used to filter which skills and knowledge sources a question is allowed to
match.
