**repo** - GitHub repository (`owner/name`) whose releases contain the decks.

**asset** - release file to import. `ijc-hsk-all.apkg` contains all decks.

**github_token** - only needed if the repository is private: a fine-grained
token with read-only *Contents* access to this one repository.

**check_on_startup** - look for a new release every time Anki opens
(after the normal startup sync). Manual check: *Tools → IJC HSK: check for updates*.

**sync_after_import** - sync with AnkiWeb right after a new release was
imported, so your phone gets the new cards. Requires being logged in to AnkiWeb.

**place_cards** – after each import, move cards to the deck the release puts
them in (e.g. lesson subdecks). Anki itself never moves existing cards on
import. Turn off if you organise these cards into decks by hand.
