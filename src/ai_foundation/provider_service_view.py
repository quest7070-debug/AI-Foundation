"""Read-only service-first projection over existing provider credentials and manual selections.

Services are the user-facing management unit; Keychain keys remain hidden
authentication sub-resources. This is not a second routing policy or store.
"""
from dataclasses import dataclass
import hashlib


@dataclass(frozen=True)
class CredentialConnection:
    reference: str
    tier: str
    observed_health: str
    stored: bool
    approved_for_model: bool
    admission_reason: str
    models: tuple[str, ...]


@dataclass(frozen=True)
class ProjectView:
    reference: str
    identity_verified: bool
    credentials: tuple[CredentialConnection, ...]


@dataclass(frozen=True)
class AccountView:
    reference: str
    identity_verified: bool
    projects: tuple[ProjectView, ...]


@dataclass(frozen=True)
class ServiceView:
    provider: str
    credentials: int
    approved_connections: int
    accounts: tuple[AccountView, ...]


def service_inventory(credentials, admission, available):
    """Render Service > Account > Project > Key > exact approved model.

    An unverified credential receives its own anonymous account/project scope.
    Never group all unverified keys as one account; they could belong to
    different billing owners. Only the trusted host's manually identified account
    may associate two keys with the same verified account/project.
    """
    services = {}
    for meta in credentials:
        provider = meta["provider"].upper()
        binding = meta["binding"]
        decision = admission.decide(meta) if admission else None
        accepted = bool(decision and decision.allowed)
        scope = admission.verified_scope(meta) if accepted else None
        if scope is None:
            opaque = hashlib.sha256(binding.encode()).hexdigest()[:16]
            account_ref = "unverified-account:" + opaque
            project_ref = "unverified-project:" + opaque
        else:
            account_ref, project_ref = scope
        key_ref = "key:" + hashlib.sha256(
            (provider + ":" + binding).encode()).hexdigest()[:16]
        present = bool(available(binding))
        connection = CredentialConnection(
            reference=key_ref,
            tier=meta["tier"],
            observed_health=meta["health"],
            stored=present,
            approved_for_model=accepted and present,
            admission_reason=("CREDENTIAL_MISSING" if not present else
                              (decision.reason if decision else "ADMISSION_NOT_CONFIGURED")),
            models=((meta["model"],) if meta.get("model") else ()),
        )
        service = services.setdefault(provider, {})
        account = service.setdefault(account_ref, {})
        project = account.setdefault(project_ref, [])
        project.append(connection)
    result = []
    for provider, accounts in sorted(services.items()):
        rendered_accounts = []
        for account_ref, projects in sorted(accounts.items()):
            rendered_projects = []
            for project_ref, connections in sorted(projects.items()):
                rendered_projects.append(ProjectView(
                    project_ref, not project_ref.startswith("unverified-project:"),
                    tuple(sorted(connections, key=lambda c: c.reference))))
            rendered_accounts.append(AccountView(
                account_ref, not account_ref.startswith("unverified-account:"),
                tuple(rendered_projects)))
        all_connections = tuple(c for a in rendered_accounts
                                for p in a.projects for c in p.credentials)
        result.append(ServiceView(
            provider, len(all_connections),
            sum(c.approved_for_model for c in all_connections),
            tuple(rendered_accounts)))
    return tuple(result)
