"""
Cloud service icon registry.

One component needs two different icon representations:

- **draw.io XML** - draw.io ships official AWS / Azure / GCP stencil libraries,
  so the exported file can carry the real vendor icon. That is what `stencil`
  holds: an mxGraph style fragment.
- **PNG preview** - services/diagram_renderer.py draws with Pillow only (no
  headless browser, no network), so it cannot load an mxGraph stencil. It draws
  a simplified glyph instead, chosen by `glyph`.

Both come from the same registry so a service looks like the same thing in the
preview and in the downloaded file.

Resolution order, most specific first:
 1. the blueprint's explicit "service" key ("s3", "lambda", ...)
 2. keyword match against the component's display name ("RDS PostgreSQL" -> rds)
 3. the generic component "type" (service / database / queue / ...)

Anything unrecognised degrades to a labelled rounded box, which is the right
failure mode: a diagram with one generic shape still reads correctly.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IconSpec:
    """How one service is drawn, in both draw.io and the PNG preview."""

    key: str          # canonical id, e.g. "s3"
    label: str        # human name, e.g. "S3"
    glyph: str        # painter id used by diagram_renderer
    stencil: str      # mxGraph style fragment, "" = plain box
    accent: str       # glyph colour in the preview
    width: int = 78
    height: int = 78


# ==================== Provider brand colours ====================
# Per-provider accent used when a service has no colour of its own.

PROVIDER_ACCENT = {
    "AWS": "#ED7100",
    "Azure": "#0078D4",
    "GCP": "#4285F4",
}
DEFAULT_ACCENT = "#5A6672"

# AWS groups its icons by category colour. Matching them makes a generated
# diagram look like the reference architectures people compare it against.
AWS_COMPUTE = "#ED7100"
AWS_STORAGE = "#7AA116"
AWS_DATABASE = "#527FFF"
AWS_NETWORK = "#8C4FFF"
AWS_INTEGRATION = "#E7157B"
AWS_SECURITY = "#DD344C"
AWS_ANALYTICS = "#8C4FFF"
AWS_MANAGEMENT = "#E7157B"


def _aws(res: str) -> str:
    """AWS4 resource-icon style. `res` is the mxgraph.aws4 stencil name."""
    return (
        "sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;"
        "fillColor=#ffffff;strokeColor=none;dashed=0;verticalLabelPosition=bottom;"
        "verticalAlign=top;align=center;html=1;fontSize=11;fontStyle=0;"
        f"aspect=fixed;shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{res};"
    )


def _aws_service(res: str) -> str:
    """AWS4 plain service icon (no coloured tile behind it)."""
    return (
        "sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;"
        "fillColor=#ffffff;strokeColor=none;dashed=0;verticalLabelPosition=bottom;"
        "verticalAlign=top;align=center;html=1;fontSize=11;fontStyle=0;"
        f"aspect=fixed;shape=mxgraph.aws4.{res};"
    )


def _azure(path: str) -> str:
    return (
        "sketch=0;points=[[0,0,0],[0.25,0,0],[0.5,0,0],[0.75,0,0],[1,0,0],"
        "[0,1,0],[0.25,1,0],[0.5,1,0],[0.75,1,0],[1,1,0],[0,0.25,0],[0,0.5,0],"
        "[0,0.75,0],[1,0.25,0],[1,0.5,0],[1,0.75,0]];outlineConnect=0;"
        "fontColor=#232F3E;fillColor=#0078D4;strokeColor=none;dashed=0;"
        "verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;"
        f"fontSize=11;fontStyle=0;aspect=fixed;shape=mxgraph.azure2.{path};"
    )


def _gcp(path: str) -> str:
    return (
        "sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;"
        "fillColor=#4284F3;strokeColor=none;dashed=0;verticalLabelPosition=bottom;"
        "verticalAlign=top;align=center;html=1;fontSize=11;fontStyle=0;"
        f"aspect=fixed;shape=mxgraph.gcp2.{path};"
    )


# ==================== Registry ====================
# key -> (label, glyph, stencil, accent, aliases)
# `aliases` are lowercase substrings matched against a component's display name.

_AWS: Dict[str, Tuple] = {
    "ec2":          ("EC2", "compute", _aws("ec2"), AWS_COMPUTE, ["ec2", "virtual machine", "instance"]),
    "lambda":       ("Lambda", "function", _aws("lambda"), AWS_COMPUTE, ["lambda", "serverless function"]),
    "ecs":          ("ECS", "container", _aws("ecs"), AWS_COMPUTE, ["ecs", "fargate", "task definition"]),
    "eks":          ("EKS", "kubernetes", _aws("eks"), AWS_COMPUTE, ["eks", "kubernetes", "k8s"]),
    "beanstalk":    ("Elastic Beanstalk", "compute", _aws("elastic_beanstalk"), AWS_COMPUTE, ["beanstalk"]),
    "batch":        ("Batch", "batch", _aws("batch"), AWS_COMPUTE, ["aws batch"]),

    "s3":           ("S3", "storage", _aws("s3"), AWS_STORAGE, ["s3", "bucket", "object storage"]),
    "efs":          ("EFS", "filestore", _aws("elastic_file_system"), AWS_STORAGE, ["efs", "file system"]),
    "glacier":      ("Glacier", "archive", _aws("s3_glacier"), AWS_STORAGE, ["glacier", "archive"]),

    "rds":          ("RDS", "database", _aws("rds"), AWS_DATABASE, ["rds", "postgres", "mysql", "mariadb", "relational"]),
    "aurora":       ("Aurora", "database", _aws("aurora"), AWS_DATABASE, ["aurora"]),
    "dynamodb":     ("DynamoDB", "nosql", _aws("dynamodb"), AWS_DATABASE, ["dynamo"]),
    "elasticache":  ("ElastiCache", "cache", _aws("elasticache"), AWS_DATABASE, ["elasticache", "redis", "memcached"]),
    "redshift":     ("Redshift", "warehouse", _aws("redshift"), AWS_DATABASE, ["redshift", "data warehouse"]),
    "documentdb":   ("DocumentDB", "nosql", _aws("documentdb"), AWS_DATABASE, ["documentdb", "mongo"]),

    "cloudfront":   ("CloudFront", "cdn", _aws("cloudfront"), AWS_NETWORK, ["cloudfront", "cdn", "edge"]),
    "elb":          ("Load Balancer", "loadbalancer", _aws("elastic_load_balancing"), AWS_NETWORK, ["load balancer", "alb", "nlb", "elb"]),
    "route53":      ("Route 53", "dns", _aws("route_53"), AWS_NETWORK, ["route 53", "route53", "dns"]),
    "apigateway":   ("API Gateway", "gateway", _aws("api_gateway"), AWS_NETWORK, ["api gateway", "apigw"]),
    "vpc":          ("VPC", "network", _aws("vpc"), AWS_NETWORK, ["vpc", "subnet", "virtual private"]),
    "directconnect": ("Direct Connect", "network", _aws("direct_connect"), AWS_NETWORK, ["direct connect"]),

    "sqs":          ("SQS", "queue", _aws("sqs"), AWS_INTEGRATION, ["sqs", "queue"]),
    "sns":          ("SNS", "topic", _aws("sns"), AWS_INTEGRATION, ["sns", "topic", "pub/sub", "notification"]),
    "eventbridge":  ("EventBridge", "events", _aws("eventbridge"), AWS_INTEGRATION, ["eventbridge", "event bus"]),
    "kinesis":      ("Kinesis", "stream", _aws("kinesis"), AWS_ANALYTICS, ["kinesis", "stream"]),
    "stepfunctions": ("Step Functions", "workflow", _aws("step_functions"), AWS_INTEGRATION, ["step function", "state machine"]),

    "cloudwatch":   ("CloudWatch", "monitor", _aws("cloudwatch_2"), AWS_MANAGEMENT, ["cloudwatch", "monitor", "metrics", "logs"]),
    "iam":          ("IAM", "identity", _aws("iam"), AWS_SECURITY, ["iam", "role", "policy"]),
    "cognito":      ("Cognito", "identity", _aws("cognito"), AWS_SECURITY, ["cognito", "user pool"]),
    "waf":          ("WAF", "firewall", _aws("waf"), AWS_SECURITY, ["waf", "web application firewall"]),
    "secrets":      ("Secrets Manager", "secret", _aws("secrets_manager"), AWS_SECURITY, ["secrets manager", "secret"]),
    "kms":          ("KMS", "key", _aws("key_management_service"), AWS_SECURITY, ["kms", "encryption key"]),
}

_AZURE: Dict[str, Tuple] = {
    "vm":           ("Virtual Machine", "compute", _azure("compute/Virtual_Machine"), "#0078D4", ["virtual machine", "vm "]),
    "appservice":   ("App Service", "compute", _azure("app_services/App_Services"), "#0078D4", ["app service", "web app"]),
    "functions":    ("Functions", "function", _azure("compute/Function_Apps"), "#0078D4", ["function app", "azure function"]),
    "aks":          ("AKS", "kubernetes", _azure("containers/Kubernetes_Services"), "#0078D4", ["aks", "kubernetes"]),
    "aci":          ("Container Instances", "container", _azure("containers/Container_Instances"), "#0078D4", ["container instance"]),

    "blob":         ("Blob Storage", "storage", _azure("storage/Storage_Accounts"), "#0078D4", ["blob", "storage account"]),
    "sql":          ("SQL Database", "database", _azure("databases/SQL_Database"), "#0078D4", ["sql database", "azure sql"]),
    "cosmos":       ("Cosmos DB", "nosql", _azure("databases/Azure_Cosmos_DB"), "#0078D4", ["cosmos"]),
    "rediscache":   ("Cache for Redis", "cache", _azure("databases/Cache_Redis"), "#0078D4", ["redis", "cache for redis"]),
    "synapse":      ("Synapse", "warehouse", _azure("databases/Azure_Synapse_Analytics"), "#0078D4", ["synapse", "data warehouse"]),

    "frontdoor":    ("Front Door", "cdn", _azure("networking/Front_Doors"), "#0078D4", ["front door", "cdn"]),
    "loadbalancer": ("Load Balancer", "loadbalancer", _azure("networking/Load_Balancers"), "#0078D4", ["load balancer"]),
    "appgateway":   ("Application Gateway", "gateway", _azure("networking/Application_Gateway"), "#0078D4", ["application gateway"]),
    "apim":         ("API Management", "gateway", _azure("app_services/API_Management_Services"), "#0078D4", ["api management", "apim"]),
    "vnet":         ("Virtual Network", "network", _azure("networking/Virtual_Networks"), "#0078D4", ["virtual network", "vnet"]),
    "dns":          ("DNS", "dns", _azure("networking/DNS_Zones"), "#0078D4", ["dns zone"]),

    "servicebus":   ("Service Bus", "queue", _azure("integration/Service_Bus"), "#0078D4", ["service bus", "queue"]),
    "eventhub":     ("Event Hubs", "stream", _azure("analytics/Event_Hubs"), "#0078D4", ["event hub"]),
    "eventgrid":    ("Event Grid", "events", _azure("integration/Event_Grid_Topics"), "#0078D4", ["event grid"]),
    "logicapps":    ("Logic Apps", "workflow", _azure("integration/Logic_Apps"), "#0078D4", ["logic app"]),

    "monitor":      ("Monitor", "monitor", _azure("management_governance/Monitor"), "#0078D4", ["azure monitor", "app insights", "monitor"]),
    "entra":        ("Entra ID", "identity", _azure("identity/Azure_Active_Directory"), "#0078D4", ["active directory", "entra", "aad"]),
    "keyvault":     ("Key Vault", "secret", _azure("security/Key_Vaults"), "#0078D4", ["key vault"]),
}

_GCP: Dict[str, Tuple] = {
    "gce":          ("Compute Engine", "compute", _gcp("compute_engine"), "#4285F4", ["compute engine", "gce"]),
    "cloudrun":     ("Cloud Run", "container", _gcp("cloud_run"), "#4285F4", ["cloud run"]),
    "functions":    ("Cloud Functions", "function", _gcp("cloud_functions"), "#4285F4", ["cloud function"]),
    "gke":          ("GKE", "kubernetes", _gcp("kubernetes_engine"), "#4285F4", ["gke", "kubernetes"]),
    "appengine":    ("App Engine", "compute", _gcp("app_engine"), "#4285F4", ["app engine"]),

    "gcs":          ("Cloud Storage", "storage", _gcp("cloud_storage"), "#4285F4", ["cloud storage", "gcs", "bucket"]),
    "cloudsql":     ("Cloud SQL", "database", _gcp("cloud_sql"), "#4285F4", ["cloud sql", "postgres", "mysql"]),
    "firestore":    ("Firestore", "nosql", _gcp("cloud_firestore"), "#4285F4", ["firestore", "datastore"]),
    "bigtable":     ("Bigtable", "nosql", _gcp("cloud_bigtable"), "#4285F4", ["bigtable"]),
    "bigquery":     ("BigQuery", "warehouse", _gcp("bigquery"), "#4285F4", ["bigquery"]),
    "memorystore":  ("Memorystore", "cache", _gcp("cloud_memorystore"), "#4285F4", ["memorystore", "redis"]),

    "cloudcdn":     ("Cloud CDN", "cdn", _gcp("cloud_cdn"), "#4285F4", ["cloud cdn", "cdn"]),
    "clb":          ("Cloud Load Balancing", "loadbalancer", _gcp("cloud_load_balancing"), "#4285F4", ["load balanc"]),
    "endpoints":    ("Cloud Endpoints", "gateway", _gcp("cloud_endpoints"), "#4285F4", ["endpoints", "api gateway"]),
    "vpc":          ("VPC", "network", _gcp("virtual_private_cloud"), "#4285F4", ["vpc", "virtual private"]),
    "clouddns":     ("Cloud DNS", "dns", _gcp("cloud_dns"), "#4285F4", ["cloud dns", "dns"]),

    "pubsub":       ("Pub/Sub", "topic", _gcp("cloud_pubsub"), "#4285F4", ["pub/sub", "pubsub"]),
    "dataflow":     ("Dataflow", "stream", _gcp("cloud_dataflow"), "#4285F4", ["dataflow"]),
    "composer":     ("Composer", "workflow", _gcp("cloud_composer"), "#4285F4", ["composer", "airflow"]),

    "monitoring":   ("Cloud Monitoring", "monitor", _gcp("cloud_monitoring"), "#4285F4", ["monitoring", "stackdriver"]),
    "iam":          ("Cloud IAM", "identity", _gcp("cloud_iam"), "#4285F4", ["iam"]),
    "armor":        ("Cloud Armor", "firewall", _gcp("cloud_armor"), "#4285F4", ["armor", "waf"]),
    "secretmanager": ("Secret Manager", "secret", _gcp("secret_manager"), "#4285F4", ["secret manager"]),
}

_REGISTRY: Dict[str, Dict[str, Tuple]] = {"AWS": _AWS, "Azure": _AZURE, "GCP": _GCP}


# ==================== Generic fallbacks ====================
# Used when nothing provider-specific matches. These keep the original 7
# component types working, so an older blueprint still renders.

_GENERIC: Dict[str, Tuple[str, str, int, int]] = {
    # type -> (glyph, mxGraph shape fragment, width, height)
    "service":   ("service", "rounded=1;whiteSpace=wrap;html=1;strokeWidth=2;", 160, 60),
    "database":  ("database", "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;"
                              "backgroundOutline=1;strokeWidth=2;", 140, 80),
    "container": ("container", "rounded=0;whiteSpace=wrap;html=1;strokeWidth=2;", 180, 60),
    "queue":     ("queue", "shape=process;whiteSpace=wrap;html=1;strokeWidth=2;", 160, 60),
    "cdn":       ("cdn", "shape=cloud;whiteSpace=wrap;html=1;strokeWidth=2;", 160, 90),
    "internet":  ("internet", "shape=cloud;whiteSpace=wrap;html=1;strokeWidth=2;", 160, 90),
    "user":      ("user", "shape=actor;whiteSpace=wrap;html=1;strokeWidth=2;", 60, 80),
}

# Component types that are people or networks rather than a vendor service -
# an AWS icon would be wrong for these even in an AWS diagram.
_PROVIDER_NEUTRAL = {"user", "internet"}

_WORD = re.compile(r"[^a-z0-9]+")


def _normalise(text: str) -> str:
    return _WORD.sub(" ", (text or "").lower()).strip()


def service_keys(provider: str) -> List[str]:
    """Canonical service keys for a provider, for the blueprint prompt."""
    return sorted(_REGISTRY.get(provider, {}).keys())


def catalogue_for_prompt(provider: str) -> str:
    """`key = Label` lines, so the model answers with keys we can resolve."""
    table = _REGISTRY.get(provider, {})
    return ", ".join(f"{key}={values[0]}" for key, values in sorted(table.items()))


def resolve(
    name: str,
    component_type: str,
    provider: str,
    service: Optional[str] = None,
) -> IconSpec:
    """
    Pick the icon for one component.

    `service` is the blueprint's explicit key and wins when it is recognised.
    Otherwise the display name is matched against each service's aliases, and
    finally the generic component type is used.
    """
    provider = provider if provider in _REGISTRY else "AWS"
    table = _REGISTRY[provider]
    kind = (component_type or "service").lower().strip()

    # People and the public internet are never a vendor service.
    if kind in _PROVIDER_NEUTRAL:
        return _generic_spec(kind, provider)

    # 1. explicit key from the blueprint
    if service:
        hit = table.get(str(service).lower().strip())
        if hit:
            return _spec(str(service).lower().strip(), hit)

    # 2. keyword match on the display name, longest alias first so that
    #    "api gateway" beats "gateway" and "cloud sql" beats "sql"
    haystack = _normalise(name)
    if haystack:
        best: Optional[Tuple[int, str, Tuple]] = None
        for key, values in table.items():
            for alias in values[4]:
                if _normalise(alias) and _normalise(alias) in haystack:
                    score = len(alias)
                    if best is None or score > best[0]:
                        best = (score, key, values)
        if best:
            return _spec(best[1], best[2])

    # 3. generic component type
    return _generic_spec(kind, provider)


def _spec(key: str, values: Tuple) -> IconSpec:
    label, glyph, stencil, accent, _aliases = values
    return IconSpec(key=key, label=label, glyph=glyph, stencil=stencil, accent=accent)


def _generic_spec(kind: str, provider: str) -> IconSpec:
    glyph, stencil, width, height = _GENERIC.get(kind, _GENERIC["service"])
    return IconSpec(
        key=kind,
        label=kind.title(),
        glyph=glyph,
        stencil=stencil,
        accent=PROVIDER_ACCENT.get(provider, DEFAULT_ACCENT),
        width=width,
        height=height,
    )


def is_vendor_icon(spec: IconSpec) -> bool:
    """True when the spec carries a real vendor stencil rather than a box."""
    return "mxgraph." in spec.stencil
