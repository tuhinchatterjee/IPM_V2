# Lab model profiles

One JSON per pinned profile. No secrets: a profile names the environment variable that holds a credential (`api_key_env`), never the key.
Identities for open-weight candidates come from the master prompt's references [R1]-[R8] and are marked `identity_source` accordingly; they were not re-fetched in the session that created them.
A tuning, quantization or reasoning variation is a NEW profile file with `parent_profile_id`, never an edit to an existing one.
`fixture-*` profiles are deterministic demonstration fixtures that drive the real engine with scripted tool calls. They are not models and are labelled FIXTURE everywhere.
Kimi and other backlog names are deliberately not registered until an exact checkpoint is verified.
