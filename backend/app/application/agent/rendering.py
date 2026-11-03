"""Player-facing rendering boundary for Agent responses."""

import re


class ResponseRenderer:
    """Clean provider protocol markers and format host narration."""

    _PROTOCOL_MARKERS = re.compile(
        r"<\|/?(?:DSML|TOOL|END)\|>|\|/?(?:DSML|TOOL|END)\|",
        flags=re.IGNORECASE,
    )
    _INTERNAL_TAGS = re.compile(
        r"</?(?:ds_system|ds_tool_call|tool_call)[^>]*>",
        flags=re.IGNORECASE,
    )
    _LIST_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+[.)、])\s+")
    _MARKDOWN_EMPHASIS = re.compile(r"\*{1,3}([^*]+)\*{1,3}")

    def clean(self, content: object) -> str:
        """Remove model/provider markers without changing the narration."""
        if not isinstance(content, str):
            return ""
        cleaned = self._PROTOCOL_MARKERS.sub("", content)
        cleaned = self._INTERNAL_TAGS.sub("", cleaned)
        cleaned = cleaned.replace("```", "")
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned.strip()

    def render_player_response(self, content: object) -> str:
        return self.clean(content)

    def render_ending(self, content: object) -> str:
        """Render an ending as continuous host narration."""
        cleaned = self.clean(content)
        if not cleaned:
            return ""

        lines: list[str] = []
        for raw_line in cleaned.replace("\r\n", "\n").split("\n"):
            line = raw_line.strip()
            if not line:
                continue

            plain_line = line.strip("* ")
            if plain_line.rstrip("：:") in {
                "完整真相",
                "角色命运",
                "本局结局",
                "案件真相与结局",
            }:
                continue

            line = self._LIST_PREFIX.sub("", line)
            line = self._MARKDOWN_EMPHASIS.sub(r"\1", line)
            lines.append(line.strip())

        return "".join(lines).strip()
