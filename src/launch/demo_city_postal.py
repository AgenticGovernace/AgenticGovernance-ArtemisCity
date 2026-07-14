#!/usr/bin/env python3

import sys
from pathlib import Path

# Add repo paths for direct execution from any working directory.
_script_file = globals().get("__file__")
_repo_root = Path(_script_file).resolve().parents[2] if _script_file else Path.cwd()
_src_root = _repo_root / "src"
for _path in (_repo_root, _src_root):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

try:
    from memory.integration import get_post_office, get_trust_interface

    MEMORY_AVAILABLE = True
except ImportError:
    MEMORY_AVAILABLE = False
    print("⚠️  Memory integration not available - running in demo mode")

    # Create mock functions for demo purposes
    class MockPostOffice:
        """Fallback postal service used when the memory integration layer is unavailable."""

        def send_mail(self, sender, recipient, subject, content, priority="normal"):
            """Simulate sending a piece of mail between two city agents.

            Args:
                sender: Agent sending the message.
                recipient: Agent receiving the message.
                subject: Message subject line.
                content: Message body content.
                priority: Delivery priority label for the mock packet.

            Returns:
                str: Human-readable summary of the simulated delivery.
            """
            return f"📧 Mail from {sender} to {recipient}: {subject}"

        def check_mailbox(self, agent):
            """Return the mock mailbox contents for an agent.

            Args:
                agent: Agent whose mailbox should be inspected.

            Returns:
                list: Empty list because the demo fallback does not persist mail.
            """
            return []

        def send_to_archives(self, sender, archive_section, title, content):
            """Simulate sending a record to the city archives.

            Args:
                sender: Agent filing the archive entry.
                archive_section: Archive section name.
                title: Archive document title.
                content: Archive document body.

            Returns:
                MockResponse: Success marker for the simulated archive write.
            """

            class MockResponse:
                """Minimal response object returned by the archive mock."""

                success = True

            return MockResponse()

        def request_from_archives(self, requester, query, section):
            """Simulate an archive search request.

            Args:
                requester: Agent requesting archived material.
                query: Search query text.
                section: Archive section being searched.

            Returns:
                list: Empty search results for the fallback implementation.
            """
            return []

        def get_postal_report(self):
            """Return a canned postal activity summary.

            Returns:
                str: Fixed report text for demo mode.
            """
            return "Mock postal report"

    class MockTrust:
        """Fallback trust service used when the real trust interface is unavailable."""

        def get_trust_score(self, citizen):
            """Return a fixed trust score object for the requested citizen.

            Args:
                citizen: Citizen identifier being evaluated.

            Returns:
                MockScore: Fixed score object representing a trusted citizen.
            """

            class MockScore:
                """Simple trust score container used by the demo fallback."""

                score = 0.75

                class MockLevel:
                    """Simple trust level container used by the demo fallback."""

                    value = "TRUSTED"

                level = MockLevel()

            return MockScore()

        def can_perform_operation(self, citizen, operation):
            """Allow every mocked operation in demo mode.

            Args:
                citizen: Citizen attempting the operation.
                operation: Operation name being authorized.

            Returns:
                bool: Always ``True`` for the fallback trust service.
            """
            return True

    def get_post_office():
        """Return the mock postal service implementation for demo mode.

        Returns:
            MockPostOffice: Mock postal service instance.
        """
        return MockPostOffice()

    def get_trust_interface():
        """Return the mock trust service implementation for demo mode.

        Returns:
            MockTrust: Mock trust service instance.
        """
        return MockTrust()


def city_welcome():
    """Welcome message for Artemis City.

    Returns:
        None: This function does not return a value.
    """
    print("\n" + "=" * 70)
    print("  WELCOME TO ARTEMIS CITY")
    print("=" * 70)
    print()
    print("A living agent ecosystem where:")
    print("    Agents are citizens with unique clearance levels")
    print("   Memory operations are mail deliveries")
    print("    The Obsidian vault serves as City Archives")
    print("   Pack Rat handles all secure postal routing")
    print("    Trust Office manages citizen clearances")
    print()
    print("=" * 70)
    print()


def demo_mail_delivery():
    """Demonstrate inter-agent mail delivery.

    Returns:
        None: This function does not return a value.
    """
    print("\n" + "=" * 70)
    print("SCENARIO 1: Inter-Agent Mail Delivery")
    print("=" * 70)
    print()
    print("Artemis wants to send a governance update to all agents...")

    post_office = get_post_office()

    # Artemis sends mail to multiple recipients
    recipients = ["pack_rat", "planner", "agentzero"]

    for recipient in recipients:
        packet = post_office.send_mail(
            sender="artemis",
            recipient=recipient,
            subject="Weekly Governance Update",
            content=f"""
Fellow citizen {recipient},

This week's governance highlights:
- ATP protocol integration complete
- Memory layer now operational
- Postal service establishing delivery routes
- All systems nominal

The city thrives through our collaboration.

— Artemis, Mayor of Artemis City
            """.strip(),
            priority="normal",
        )

        print(f"\n   {packet}")
        input("\n   Press Enter to continue to next delivery...")

    print("\n All mail delivered successfully!")


def demo_mailbox_check():
    """Demonstrate checking agent mailboxes.

    Returns:
        None: This function does not return a value.
    """
    print("\n\n" + "=" * 70)
    print("SCENARIO 2: Checking Mailboxes")
    print("=" * 70)
    print()
    print("Pack Rat checks their mailbox for new deliveries...")

    post_office = get_post_office()

    # Check Pack Rat's mailbox
    mail = post_office.check_mailbox("pack_rat")

    if mail:
        print(f"\n    Pack Rat has mail!")
        print(f"   Review the items above for details")
    else:
        print(f"\n   📭 No mail yet (vault may be empty or MCP not connected)")

    input("\n   Press Enter to continue...")


def demo_archival_system():
    """Demonstrate City Archives filing.

    Returns:
        None: This function does not return a value.
    """
    print("\n\n" + "=" * 70)
    print("SCENARIO 3: City Archives")
    print("=" * 70)
    print()
    print("Artemis files a reflection in the City Archives...")

    post_office = get_post_office()

    reflection = """
# Weekly Reflection - City Operations

## Accomplishments
- Postal service operational
- Inter-agent communication established
- Trust clearances functioning
- Pack Rat handling deliveries efficiently

## Observations
- Citizens collaborating effectively
- Archive system organizing knowledge well
- Trust decay model maintaining security

## Next Steps
- Enhance routing efficiency
- Add more archive sections
- Monitor citizen clearance levels

The city is alive and thriving.
    """.strip()

    response = post_office.send_to_archives(
        sender="artemis",
        archive_section="Reflections",
        title="Weekly_Operations_Report",
        content=reflection,
    )

    if response.success:
        print("\n    Reflection successfully archived!")

    input("\n   Press Enter to continue...")


def demo_archive_search():
    """Demonstrate searching City Archives.

    Returns:
        None: This function does not return a value.
    """
    print("\n\n" + "=" * 70)
    print("SCENARIO 4: Archive Research")
    print("=" * 70)
    print()
    print("Copilot searches archives for governance information...")

    post_office = get_post_office()

    results = post_office.request_from_archives(
        requester="planner", query="governance", section="Reflections"
    )

    if results:
        print(f"\n    Research successful!")
        print(f"   Copilot can now reference historical documents")
    else:
        print(f"\n   📭 No archived documents found yet")
        print(f"   (This is expected on first run)")

    input("\n   Press Enter to continue...")


def demo_trust_clearances():
    """Demonstrate trust-based clearance system.

    Returns:
        None: This function does not return a value.
    """
    print("\n\n" + "=" * 70)
    print("SCENARIO 5: Citizen Clearance Levels")
    print("=" * 70)
    print()
    print("The Trust Office manages citizen clearances...")

    trust = get_trust_interface()

    print("\n     CURRENT CITIZEN CLEARANCES")
    print("   " + "=" * 60)

    citizens = ["artemis", "pack_rat", "agentzero", "planner"]

    for citizen in citizens:
        score = trust.get_trust_score(citizen)

        # Visualize trust level
        bar_length = int(score.score * 20)
        trust_bar = "█" * bar_length + "░" * (20 - bar_length)

        print(f"\n   {citizen:15}")
        print(f"     Level: {score.level.value:10} [{trust_bar}] {score.score:.2f}")
        print(f"     Clearances: ", end="")

        # Show what they can do
        can_read = "📖 Read" if trust.can_perform_operation(citizen, "read") else ""
        can_write = "✍️  Write" if trust.can_perform_operation(citizen, "write") else ""
        can_delete = (
            "🗑️  Delete" if trust.can_perform_operation(citizen, "delete") else ""
        )

        clearances = [c for c in [can_read, can_write, can_delete] if c]
        print(" | ".join(clearances))

    print("\n   " + "=" * 60)

    input("\n   Press Enter to continue...")


def demo_postal_report():
    """Generate final postal service report.

    Returns:
        None: This function does not return a value.
    """
    print("\n\n" + "=" * 70)
    print("FINALE: Postal Service Report")
    print("=" * 70)
    print()
    print("Generating city-wide activity report...")

    post_office = get_post_office()
    report = post_office.get_postal_report()

    print("\n End of Day Summary")
    print("=" * 70)
    print()
    print("The Post Office processed all mail efficiently.")
    print("Pack Rat performed admirably in delivery duties.")
    print("All citizens maintained their clearance levels.")
    print("The City Archives grew with new knowledge.")
    print()
    print("Artemis City thrives through collaboration!")
    print()
    print("=" * 70)


def main():
    """Run the Artemis City postal service demonstration.

    Returns:
        None: This function does not return a value.
    """

    city_welcome()

    print("This demo showcases the living city theme where:")
    print("  • Agents communicate through postal mail")
    print("  • Pack Rat delivers all messages securely")
    print("  • Trust Office manages citizen clearances")
    print("  • City Archives preserve institutional knowledge")
    print()
    print("Note: MCP server must be running for full functionality.")
    print("      Demo will work offline with simulated responses.")
    print()

    try:
        input("Press Enter to begin the city tour...")

        # Run scenarios
        demo_mail_delivery()
        demo_mailbox_check()
        demo_archival_system()
        demo_archive_search()
        demo_trust_clearances()
        demo_postal_report()

        # Closing
        print("\n\n" + "=" * 70)
        print("  THANK YOU FOR VISITING ARTEMIS CITY")
        print("=" * 70)
        print()
        print("You've seen how agents in Artemis City:")
        print("   Send and receive mail through Pack Rat")
        print("   File documents in City Archives")
        print("   Maintain trust-based clearances")
        print("   Collaborate as citizens of a living ecosystem")
        print()
        print("The city is ready for your agents to move in!")
        print()
        print("=" * 70)
        print()

    except KeyboardInterrupt:
        print("\n\n👋 Goodbye from Artemis City!")
        print()
    except Exception as e:
        print(f"\n\n  City services encountered an issue: {e}")
        print("This may be because MCP server is not running.")
        print("The demo requires MCP_BASE_URL and MCP_API_KEY environment variables.")
        print()


if __name__ == "__main__":
    main()
