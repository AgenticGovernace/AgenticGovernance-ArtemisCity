"""Artemis City Postal Service - Memory delivery system.

This module provides a postal-themed interface for memory operations,
treating the Obsidian vault as the City Archives and memory operations
as mail delivery between agents.
"""

import random
import time
import datetime
import typing
import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


import integration.context_loader as context_loader
import integration.memory_client
import integration.trust_interface


class MailPacket:
    """Represents a mail packet being delivered through the city.

    Attributes:
        sender: Agent sending the mail
        recipient: Target agent or vault location
        subject: Mail subject line
        content: Mail content
        priority: Delivery priority (urgent, normal, low)
        timestamp: When mail was created
        delivery_status: Current status
        tracking_id: Unique tracking identifier
    """

    def __init__(
        self,
        sender: str,
        recipient: str,
        subject: str,
        content: str,
        priority: str = "normal",
    ) -> None:
        """Initialize a mail packet."""
        self.sender: str = sender
        self.recipient: str = recipient
        self.subject: str = subject
        self.content: str = content
        self.priority: str = priority
        self.timestamp: datetime.datetime = datetime.datetime.now()
        self.delivery_status = "created"
        self.tracking_id: str = f"{sender[:3].upper()}-{int(time.time() * 1000) % 100000}"

    def __str__(self) -> str:
        """Return a string representation of the mail packet."""
        return (
            f"[Mail #{self.tracking_id}]\n"
            f"  From: {self.sender}\n"
            f"  To: {self.recipient}\n"
            f"  Subject: {self.subject}\n"
            f"  Priority: {self.priority}\n"
            f"  Status: {self.delivery_status}"
        )


class PostOffice:
    def __init__(self) -> None:
        self.memory_client = integration.memory_client.MemoryClient()
        self.trust_office: integration.trust_interface.TrustInterface = integration.trust_interface.get_trust_interface()
        self.context_loader = context_loader.ContextLoader(self.memory_client)
        self.delivery_log: typing.List[typing.Dict] = []

        print("\n Artemis City Post Office - OPEN")
        print("=" * 60)
        print("  Serving the citizens of Artemis City")
        print("  All mail handled by Pack Rat for secure delivery")
        print("  Archives maintained in the City Library")
        print("=" * 60)

    def send_mail(
        self,
        sender: str,
        recipient: str,
        subject: str,
        content: str,
        priority: str = "normal",
    ) -> MailPacket:
        """Send mail through the postal system.

        Args:
            sender: Agent sending the mail
            recipient: Target agent or vault location
            subject: Mail subject
            content: Mail content
            priority: Delivery priority

        Returns:
            MailPacket with delivery status
        """
        packet = MailPacket(sender, recipient, subject, content, priority)

        print("\n NEW MAIL at Post Office")
        print(f"   Tracking ID: {packet.tracking_id}")
        print(f"   From: {sender} → To: {recipient}")
        print(f"   Subject: {subject}")

        # Check sender clearance
        if not self.trust_office.can_perform_operation(sender, "write"):
            packet.delivery_status = "rejected - insufficient clearance"
            print(f"    REJECTED: {sender} lacks postal clearance")
            self._log_delivery(packet, success=False, reason="No clearance")
            return packet

        # Simulate Pack Rat handling
        print("\n    Pack Rat is securing the mail...")
        time.sleep(random.uniform(0.3, 0.8))

        # Simulate potential delivery issues
        if random.random() < 0.05:  # 5% chance of delay
            print("     Temporary postal delay detected...")
            time.sleep(random.uniform(0.5, 1.0))

        # Deliver to City Archives
        vault_path: str = f"Postal/Agents/{recipient}/{packet.tracking_id}.md"

        # Create mail note
        mail_content: str = self._format_mail_note(packet)
        response: integration.memory_client.MCPResponse = self.memory_client.append_context(vault_path, mail_content)

        if response.success:
            packet.delivery_status = "delivered"
            print("    DELIVERED to City Archives")
            print(f"   📍 Location: {vault_path}")

            # Update trust
            self.trust_office.record_success(sender)

            # Tag the mail
            self.memory_client.manage_tags(
                vault_path, "add", [sender, recipient, "postal-mail", priority]
            )
        else:
            packet.delivery_status = "failed"
            print(f"    DELIVERY FAILED: {response.error}")
            self.trust_office.record_failure(sender)

        self._log_delivery(packet, response.success)
        return packet
        if mail:
            print(f"   📨 Found {len(mail)} mail item(s)")
            for i, item in enumerate(mail[:5], 1):
                print(f"      {i}. {item.path}")
        else:
            print("   📭 Mailbox is empty")

        return mail

    def send_to_archives(
        self, sender: str, archive_section: str, title: str, content: str
    ) -> integration.memory_client.MCPResponse:
        """Send a document to the City Archives for permanent storage.

        Args:
            sender: Agent filing the document
            archive_section: Section of archives (e.g., "Reflections", "Reports")
            title: Document title
            content: Document content

        Returns:
            MCPResponse with delivery status
        """
        print("\n  ARCHIVAL REQUEST")
        print(f"   From: {sender}")
        print(f"   Section: {archive_section}")
        print(f"   Title: {title}")

        # Check clearance
        if not self.trust_office.can_perform_operation(sender, "write"):
            print("    DENIED: Insufficient archival clearance")
            return integration.memory_client.MCPResponse(
                success=False, error="Insufficient clearance for archival operations"
            )

        print("\n    Pack Rat is processing archival request...")
        time.sleep(random.uniform(0.4, 0.9))

        # Store in archives
        path: str = f"Archives/{archive_section}/{sender}_{title}.md"
        response: integration.memory_client.MCPResponse = self.memory_client.store_agent_context(
            sender, content, folder=f"Archives/{archive_section}"
        )

        if response.success:
            print(f"    ARCHIVED at: {path}")
            print("    Available for future reference")
            self.trust_office.record_success(sender)
        else:
            print(f"    ARCHIVAL FAILED: {response.error}")
            self.trust_office.record_failure(sender)

        return response

    def request_from_archives(
        self, requester: str, query: str, section: typing.Optional[str] = None
    ) -> typing.List[context_loader.ContextEntry]:
        """Request documents from the City Archives.

        Args:
            requester: Agent requesting documents
            query: Search query
            section: Optional specific archive section

        Returns:
            List of matching archive documents
        """
        print("\n📖 ARCHIVE REQUEST")
        print(f"   Requester: {requester}")
        print(f"   Query: '{query}'")
        if section:
            print(f"   Section: {section}")

        # Check read clearance
        if not self.trust_office.can_perform_operation(requester, "read"):
            print("    DENIED: No archive access clearance")
            return []

        print("\n    City Librarian is searching...")
        time.sleep(random.uniform(0.5, 1.0))

        # Search archives
        search_query: str = query
        if section:
            search_query: str = f"#Archives #{section} {query}"

        results: typing.List[context_loader.ContextEntry] = self.context_loader.search_context(search_query, limit=10)

        if results:
            print(f"    Found {len(results)} document(s)")
            for i, doc in enumerate(results[:5], 1):
                print(f"      {i}. {doc.path}")
        else:
            print("   📭 No documents found matching query")

        self.trust_office.record_success(requester)
        return results

    def get_postal_report(self) -> typing.Dict:
        """Generate a postal service activity report.

        Returns:
            Dictionary with postal statistics
        """
        print("\n POSTAL SERVICE REPORT")
        print(f"   Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        total_deliveries: int = len(self.delivery_log)
        successful: int = sum(1 for d in self.delivery_log if d["success"])
        failed: int = total_deliveries - successful

        print(f"   Total Deliveries: {total_deliveries}")
        print(f"    Successful: {successful}")
        print(f"    Failed: {failed}")

        if total_deliveries > 0:
            success_rate: float = (successful / total_deliveries) * 100
            print(f"   📈 Success Rate: {success_rate:.1f}%")

        # Trust report
        print("\n     CITIZEN CLEARANCE STATUS")
        trust_report = self.trust_office.get_trust_report()
        for level, entities in trust_report["by_level"].items():
            if entities:
                print(f"   {level.upper()}: {len(entities)} citizen(s)")

        print("=" * 60)

        return {
            "total_deliveries": total_deliveries,
            "successful": successful,
            "failed": failed,
            "trust_report": trust_report,
        }

    def _format_mail_note(self, packet: MailPacket) -> str:
        """Format a mail packet as a markdown note.

        Args:
            packet: MailPacket to format

        Returns:
            Formatted markdown content
        """
        return f"""
--- 
from: {packet.sender}
to: {packet.recipient}
tracking_id: {packet.tracking_id}
priority: {packet.priority}
date: {packet.timestamp.isoformat()}
status: {packet.delivery_status}
---

# Mail: {packet.subject}

**From:** {packet.sender}
**To:** {packet.recipient}
**Date:** {packet.timestamp.strftime('%Y-%m-%d %H:%M:%S')}
**Tracking:** {packet.tracking_id}

---

{packet.content}

---

*Delivered by Pack Rat Postal Service*
*Archives maintained by Artemis City Library*
"""

    def _log_delivery(
        self, packet: MailPacket, success: bool, reason: typing.Optional[str] = None
    ) -> None:
        """Log a delivery attempt."""
        self.delivery_log.append(
            {
                "tracking_id": packet.tracking_id,
                "sender": packet.sender,
                "recipient": packet.recipient,
                "subject": packet.subject,
                "priority": packet.priority,
                "timestamp": packet.timestamp,
                "success": success,
                "reason": reason,
                "status": packet.delivery_status,
            }
        )


# Global Post Office instance
_city_post_office = None


def get_post_office() -> PostOffice:
    """Get or create the City Post Office instance.

    Returns:
        Global PostOffice instance
    """
    global _city_post_office
    if _city_post_office is None:
        _city_post_office = PostOffice()
    return _city_post_office
