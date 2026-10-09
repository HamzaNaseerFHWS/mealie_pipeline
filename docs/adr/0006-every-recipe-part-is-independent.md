# Every Recipe Part is independent

A Video can contain several recipes. Each Recipe Part gets its own Item Key (`platform:video_id#n`), its own slice of the Sources, its own extraction, Grounding (quotes only from its own slice), parse, tags, Quality Score, Review Queue entry and Mealie recipe. One part failing never blocks the others. Pipeline state is therefore tracked per Recipe Part after the outline step, and per Video before it.
