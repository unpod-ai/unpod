import json
import logging
import random
import urllib.parse

from django.http import Http404
from rest_framework import viewsets, status
from rest_framework.permissions import (
    IsAuthenticated,
    AllowAny,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.response import Response

from unpod.common.constants import PUBLIC_EMAIL_DOMAIN
from unpod.core_components.models import Pilot
from unpod.users.models import UserBasicDetail
from unpod.common.enum import (
    PrivacyType,
    SpaceType,
    KnowledgeBaseContentType,
)
from unpod.common.helpers.global_helper import (
    format_validation_errors,
    get_product_id,
)
from unpod.email_journey.services import start_journey
from unpod.notification.models import Notification
from unpod.notification.services import createNotification

from unpod.common.exception import APIException206
from unpod.common.mixin import QueryOptimizationMixin
from unpod.common.pagination import UnpodCustomPagination
from unpod.common.renderers import UnpodJSONRenderer

from unpod.common.serializer import CommonSerializer
from unpod.common.validation import Validation, fetch_email_domain, validate_email_type
from unpod.knowledge_base.utils import (
    update_store_schema,
)
from unpod.notification.utlis import expireNotification
from unpod.roles.constants import (
    DEFAULT_ORGANIZATION_PERMISSION_ROLE,
    DEFAULT_SPACE_PERMISSION_ROLE,
)
from unpod.roles.models import Roles
from unpod.roles.services import (
    getRole,
    processDeletePermission,
    processUpdatePermission,
)
from unpod.roles.utlis import getTag
from unpod.space.constants import (
    DEFAULT_SPACES,
    SPACE_LIST_ALL,
    CONTACT_SPACE_DEFAULT_SCHEMA,
)
from unpod.space.models import (
    OrganizationAccessRequest,
    OrganizationInvite,
    OrganizationMemberRoles,
    Space,
    SpaceAccessRequest,
    SpaceInvite,
    SpaceMemberRoles,
    SpaceOrganization,
    SpaceOrganizationBillingInfo,
)
from unpod.knowledge_base.models import KnowledgeBaseConfig, KnowledgeBaseEvals
from unpod.space.serializers import (
    OrgUpdateSerializers,
    SpaceAccessRequestUpdateSerializer,
    SpaceCreateSerializers,
    SpaceDetailSerializers,
    SpaceListSerializers,
    SpaceOrgDetailSerializers,
    BillingInfoRetrieveSerializer,
    BillingInfoSerializer,
    SpaceOrganizationCreateSerializers,
    SpaceOrganizationSerializers,
    SpaceRolePermissionCreateSerializer,
    SpaceUpdateSerializers,
)
from unpod.space.services import (
    AccessRequestService,
    add_org,
    checkJoinOrgInvite,
    get_space_invitation_data,
    processInvitation,
    sendInviteMail,
    fetch_space_analytics,
    createSpace, get_calls, get_task_details,
)
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models import Q

from unpod.space.utils import (
    checkOrgAccess,
    checkOrgOperationAccess,
    checkSpaceAccess,
    checkSpaceOperationAccess,
    checkSpaceOrg,
    checkSpaceSlug,
    get_last_thread,
    get_space_annotate_query,
    getAllSpaceQuerySet,
    checkOrgMemberAccess,
    checkSpaceMemberAccess,
)
from unpod.thread.models import PostBlockList, ThreadPost, ThreadPostPermission
from unpod.thread.services import makePostPrivateForSpace
from unpod.users.utils import get_name

logger = logging.getLogger(__name__)
User = get_user_model()


class SpaceOrganizationViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticatedOrReadOnly]
    serializer_class = CommonSerializer
    renderer_classes = [UnpodJSONRenderer]

    def create(self, request, *args, **kwargs):
        ser = SpaceOrganizationCreateSerializers(data=request.data)
        check_data = ser.is_valid()
        if not check_data:
            return Response(
                {"message": format_validation_errors(ser.errors)},
                status=206,
            )

        input_data = ser.validated_data
        user = request.user
        if user.organization:
            return Response({"message": "You already have an Organization"}, status=206)
        domain = fetch_email_domain(user.email)
        is_private_domain = validate_email_type(user.email)
        if input_data["domain_handle"] in PUBLIC_EMAIL_DOMAIN:
            return Response({"message": "Public Domain is not allowed"}, status=206)
        check_org = SpaceOrganization.objects.filter(
            domain_handle=input_data["domain_handle"],
            is_private_domain=is_private_domain,
        ).first()
        if check_org:
            return Response(
                {"message": "Organization for this domain already exists"}, status=206
            )
        account_type = input_data.get("account_type")
        account_type = getTag(account_type)
        organization = SpaceOrganization.objects.create(
            name=input_data["name"],
            description=input_data.get("description", ""),
            domain_handle=input_data["domain_handle"],
            domain=domain,
            is_private_domain=validate_email_type(user.email),
            account_type=account_type,
            color=input_data.get("color").upper(),
            logo=input_data.get("logo"),
            region=input_data.get("region", "IN"),
            created_by=user.id,
            updated_by=user.id,
        )
        role, created = Roles.objects.get_or_create(
            role_code="owner", role_type="organization"
        )
        org_user_role, created = OrganizationMemberRoles.objects.get_or_create(
            user=user,
            organization=organization,
            role=role,
        )
        org_user_role.created_by = user.id
        org_user_role.updated_by = user.id
        org_user_role.grant_by = user.id
        org_user_role.save()
        if hasattr(user, "userbasicdetail_user"):
            user.userbasicdetail_user.active_organization = organization
            user.userbasicdetail_user.save()

        for space in DEFAULT_SPACES:
            space_data = {
                "name": space.title(),
                "description": space.title(),
                "privacy_type": PrivacyType.public.name,
                "space_type": SpaceType.general.name,
                "content_type": KnowledgeBaseContentType.contact.name,
                "schema": CONTACT_SPACE_DEFAULT_SCHEMA,
            }

            space_obj = createSpace(space_data, user, organization)

            if hasattr(user, "userbasicdetail_user"):
                user.userbasicdetail_user.active_space = space_obj
                user.userbasicdetail_user.save()

        # Onboarding email journey: best-effort, must never fail org creation.
        try:
            start_journey(organization, user, get_product_id())
        except Exception:
            logger.exception("email_journey: start failed for org %s", organization.id)

        data = SpaceOrganizationSerializers(organization).data
        return Response(
            {"message": "Organization created successfully", "data": data}, status=200
        )

    def check(self, request, *args, **kwargs):
        domain = request.GET.get("domain")
        exclude = request.GET.get("exclude")
        if domain in PUBLIC_EMAIL_DOMAIN:
            return Response(
                {"message": "Public Domain is not allowed", "exists": True}, status=200
            )
        querySet = SpaceOrganization.objects.filter(domain_handle=domain)

        if exclude:
            querySet = querySet.exclude(id=exclude)

        organization = querySet.first()

        if organization:
            return Response(
                {
                    "message": "Organization for this domain already exists",
                    "exists": True,
                },
                status=200,
            )
        return Response(
            {"message": "Organization does not exists", "exists": False}, status=200
        )

    def join(self, request, *args, **kwargs):
        if request.user.is_anonymous:
            return Response(
                {"message": "Please Login to join the Organization"}, status=206
            )
        domain_handle = kwargs.get("domain_handle")
        check_org = SpaceOrganization.objects.filter(
            domain_handle=domain_handle
        ).first()
        if check_org:
            return Response({"message": "Invalid Token"}, status=206)
        user = request.user
        if user.organization:
            return Response(
                {"message": "You already joined an Organization"}, status=206
            )
        role, created = Roles.objects.get_or_create(
            role_code="viewer", role_type="organization"
        )
        org_user_role, created = OrganizationMemberRoles.objects.get_or_create(
            user=user,
            organization=check_org,
            role=role,
        )
        org_user_role.created_by = user.id
        org_user_role.updated_by = user.id
        org_user_role.grant_by = user.id
        org_user_role.save()
        if hasattr(user, "userbasicdetail_user"):
            user.userbasicdetail_user.active_organization = check_org
            user.userbasicdetail_user.save()
        return Response({"message": "Organization joined successfully"}, status=200)

    def action(self, request, *args, **kwargs):
        action = request.data.get("action")
        required_fields = []
        if action == "seeking":
            required_fields = ["seeking"]
        elif action == "tags":
            required_fields = ["tags"]
        elif action == "change":
            required_fields = ["domain_handle"]
        else:
            return Response({"message": "Invalid Action"}, status=206)
        validate = Validation(required_fields, request.data)
        if not validate.check_required_fields():
            return Response(
                {"message": "Required Fields Missing", "errors": validate.get_error()},
                status=206,
            )
        validate.setData()
        input_data = validate.get_data()
        user = request.user
        if not user.organization:
            return Response(
                {"message": "You are not part of any Organization"}, status=206
            )
        if action in ["seeking", "tags"]:
            organization = user.organization
            tags = input_data[action]
            getattr(organization, action).remove(*getattr(organization, action).all())
            for tag in tags:
                tag = getTag(tag)
                if tag:
                    getattr(organization, action).add(tag)
            data = SpaceOrganizationSerializers(organization).data
            return Response(
                {"message": "Organization updated successfully", "data": data},
                status=200,
            )
        check_org = OrganizationMemberRoles.objects.filter(
            user=user, organization__domain_handle=input_data["domain_handle"]
        ).first()
        if not check_org:
            return Response(
                {"message": "You are not part of this Organization"}, status=206
            )
        organization = check_org.organization
        if hasattr(user, "userbasicdetail_user"):
            user.userbasicdetail_user.active_organization = organization
            user.userbasicdetail_user.save()
        data = SpaceOrganizationSerializers(organization).data
        return Response(
            {"message": "Organization Changed successfully", "data": data}, status=200
        )

    def get_organization_detail(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        check_org = (
            SpaceOrganization.objects.filter(
                domain_handle=domain_handle, status="active"
            )
            .prefetch_related("organizationmemberroles_organization")
            .first()
        )
        if not check_org:
            return Response({"message": "Invalid Domain Handle"}, status=206)
        try:
            org_role = checkOrgAccess(request.user, check_org)
        except APIException206 as ex:
            if (
                str(ex.detail.get("message"))
                == "You Don't have Access to this Organization"
            ):
                cond = {
                    "user_email": request.user.email,
                    "organization_id": check_org.id,
                }
                invitation_data = get_space_invitation_data(
                    cond=cond, invite_type="organization"
                )
                res = {**ex.detail}
                common_data = {
                    "domain_handle": domain_handle,
                    "name": check_org.name,
                    "token": check_org.token,
                    "privacy_type": check_org.privacy_type,
                    "joined": False,
                    "final_role": DEFAULT_ORGANIZATION_PERMISSION_ROLE,
                }
                if len(invitation_data):
                    res.update(
                        {
                            "data": {
                                **invitation_data[0],
                                **common_data,
                                "is_invited": True,
                            }
                        }
                    )
                else:
                    check_request = OrganizationAccessRequest.objects.filter(
                        organization=check_org,
                        user=request.user,
                        is_joined=False,
                        is_expired=False,
                    ).first()
                    res.update({"data": {**common_data, "is_invited": False}})
                    res.update({"is_requested": check_request != None, "joined": False})
                    if check_request:
                        res.update({"request_token": check_request.request_token})
                        res.update({"request_role": check_request.role.role_code})
                return Response(res, status=206)
            raise ex

        if request.user.is_authenticated:
            if hasattr(request.user, "userbasicdetail_user"):
                if request.user.userbasicdetail_user.active_organization != check_org:
                    # Use update() instead of save() to avoid lock contention
                    UserBasicDetail.objects.filter(user=request.user).update(
                        active_organization=check_org
                    )

        data = SpaceOrgDetailSerializers(check_org, context={"request": request}).data
        check_request = OrganizationAccessRequest.objects.filter(
            organization=check_org,
            user=request.user,
            is_joined=False,
            is_expired=False,
        ).first()
        if check_request:
            data["is_requested"] = True
            data["request_token"] = check_request.request_token

        return Response(
            {
                "message": "Organization fetched successfully",
                "data": data,
            },
            status=200,
        )

    def update_organization(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        check_org = SpaceOrganization.objects.filter(
            domain_handle=domain_handle, status="active"
        ).first()
        if not check_org:
            return Response({"message": "Invalid Domain Handle"}, status=206)
        org_role = checkOrgAccess(request.user, check_org, check_role=True)
        checkOrgOperationAccess(request.user, org_role)
        ser = OrgUpdateSerializers(data=request.data, instance=check_org)
        check_data = ser.is_valid()
        if not check_data:
            return Response(
                {"errors": ser.errors, "message": "Required Parameter Missing"},
                status=206,
            )
        file = ser.validated_data.pop("logo", None)
        account_type = ser.validated_data.pop("account_type", None)
        account_type = getTag(account_type)
        if account_type:
            ser.validated_data["account_type_id"] = account_type.id
        seeking = ser.validated_data.pop("seeking", None)
        tags = ser.validated_data.pop("tags", None)
        account_type = getTag(account_type)
        if account_type:
            ser.validated_data["account_type_id"] = account_type.id
        if len(ser.validated_data):
            SpaceOrganization.objects.filter(id=check_org.id).update(
                **ser.validated_data
            )
        if file:
            check_org.logo = file
            check_org.save()
        if seeking:
            check_org.seeking.remove(*check_org.seeking.all())
            for tag in seeking:
                tag = getTag(tag)
                if tag:
                    check_org.seeking.add(tag)
        if tags:
            check_org.tags.remove(*check_org.tags.all())
            for tag in tags:
                tag = getTag(tag)
                if tag:
                    check_org.tags.add(tag)
        check_org.refresh_from_db()
        data = SpaceOrganizationSerializers(
            check_org, context={"request": request}
        ).data

        return Response(
            {"message": "Organization updated successfully", "data": data}, status=200
        )

    def archive_organization(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        check_org = SpaceOrganization.objects.filter(
            domain_handle=domain_handle, status="active"
        ).first()
        if not check_org:
            return Response({"message": "Invalid Domain Handle"}, status=206)
        org_role = checkOrgAccess(request.user, check_org, check_role=True)
        if org_role.role.role_code != "owner":
            return Response(
                {"message": "Only owner can archive the Organization"}, status=206
            )
        SpaceOrganization.objects.filter(id=check_org.id).update(status="archive")
        return Response({"message": "Organization archived successfully"}, status=200)

    def allowed_space(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        check_org = SpaceOrganization.objects.filter(
            domain_handle=domain_handle, status="active"
        ).first()
        if not check_org:
            return Response({"message": "Invalid Domain Handle"}, status=206)
        try:
            org_role = checkOrgAccess(request.user, check_org, check_role=True)
        except APIException206 as ex:
            return Response(
                {"data": [], "message": str(ex.detail.get("message"))}, status=200
            )
        space_list = None
        if org_role.role.role_code in ["owner", "editor"]:
            space_list = Space.objects.filter(
                space_type=SpaceType.general.name,
                space_organization_id=check_org.id,
                status="active",
            )
        else:
            space_query = Q(
                user=request.user,
                space__privacy_type__in=["shared", "link"],
                role__role_code__in=["editor", "owner"],
            )
            space_objs = (
                SpaceMemberRoles.objects.filter(
                    space__space_type=SpaceType.general.name,
                    space__space_organization_id=check_org.id,
                )
                .filter(space_query)
                .values_list("space_id", flat=True)
            )
            space_list = Space.objects.filter(id__in=list(space_objs), status="active")
        space_list = space_list.order_by("name").values(*SPACE_LIST_ALL)
        return Response(
            {"data": space_list, "message": "Space fetched successfully"}, status=200
        )


class SpaceViewSet(QueryOptimizationMixin, viewsets.GenericViewSet):
    """
    Phase 2.2: Refactored to use QueryOptimizationMixin for query optimization.
    """
    permission_classes = [IsAuthenticatedOrReadOnly]
    serializer_class = CommonSerializer
    renderer_classes = [UnpodJSONRenderer]

    def create(self, request, *args, **kwargs):
        ser = SpaceCreateSerializers(data=request.data)
        check_data = ser.is_valid()
        if not check_data:
            return Response(
                {"errors": ser.errors, "message": "Required Parameter Missing"},
                status=206,
            )
        input_data = ser.validated_data
        user = request.user
        organization = user.organization
        if not organization:
            domain = fetch_email_domain(user.email)
            organization = SpaceOrganization.objects.create(
                name=input_data["name"],
                domain=domain,
                is_private_domain=validate_email_type(user.email),
                account_type=input_data.get("account_type"),
                created_by=user.id,
                updated_by=user.id,
            )

        space_obj = createSpace(input_data, user, organization)

        space_data = SpaceDetailSerializers(
            space_obj, context={"request": request}
        ).data

        return Response(
            {"data": space_data, "message": "Space Successfully Created"}, status=201
        )

    def list(self, request, *args, **kwargs):
        space_list = []
        case = request.GET.get("case")
        space_type = request.GET.get("space_type", SpaceType.general.name)
        space_querset = getAllSpaceQuerySet(
            request,
            bypass_org=case in ["home", "shared"],
            case=case,
            space_type=space_type,
        )
        if case in ["all", "home", "shared", "pilot"]:
            if case == "pilot":
                space_querset = space_querset.exclude(content_type="evals")
            space_count = space_querset.count()
            space_ids = list(space_querset.values_list("id", flat=True))
            org_ids = list(
                space_querset.values_list("space_organization_id", flat=True)
            )
            space_list = get_space_annotate_query(space_querset, request)
            # space_list = space_list.extra(select={
            #     'public_main_post_slug': 'SELECT slug FROM thread_threadpost  WHERE (thread_threadpost.space_id = space_space.id) AND (thread_threadpost.post_rel = "main_post") AND (thread_threadpost.privacy_type = "public") AND (NOT thread_threadpost.is_deleted) ORDER BY thread_threadpost.id DESC LIMIT 1',
            # })
            space_list = space_list.order_by("-unread_count", "-total_post", "-id")
            # print(space_list.values('public_read_count', 'public_total_post', 'private_read_count', 'private_total_post', 'blocked_post', 'unread_count', 'total_post'))
            # space_list = space_querset.annotate(last_thread_id = Coalesce(Max('threadpost_space__id', filter=Q(threadpost_space__post_rel__in=['main_post', 'seq_post'])), 0)).order_by('-last_thread_id', '-id')
            # space_list = SpaceListAllSerializers(space_list, many=True).data
            blocked_ids = PostBlockList.objects.filter(
                post__is_deleted=False,
                user_id=request.user.id,
                post__space_id__in=list(space_ids),
                post__post_rel="main_post",
            ).values_list("post_id", flat=True)
            blocked_ids = list(blocked_ids)

            private_threads = (
                ThreadPostPermission.objects.filter(
                    post__is_deleted=False,
                    user_id=request.user.id,
                    post__space_id__in=list(space_ids),
                    post__post_rel="main_post",
                    post__privacy_type__in=["private", "shared", "link"],
                )
                .exclude(post__id__in=blocked_ids)
                .values("post__space_id", "post__slug")
                .order_by("-post_id")
            )
            public_threads = (
                ThreadPost.objects.filter(
                    space_id__in=list(space_ids),
                    post_rel="main_post",
                    privacy_type="public",
                )
                .exclude(id__in=blocked_ids)
                .values("space_id", "slug")
                .order_by("-post_id")
            )
            org_obj = SpaceOrganization.objects.filter(id__in=org_ids)
            evals_map = {}
            if space_type == "knowledge_base":
                space_tokens = list(space_querset.values_list("token", flat=True))
                evals_map = KnowledgeBaseEvals.objects.filter(
                    eval_type="knowledgebase", linked_handle__in=space_tokens
                ).values("eval_name", "linked_handle", "gen_status", "eval_data")
                eval_space_tokens = []
                for item in evals_map:
                    if item.get("eval_data", {}).get("space_token"):
                        eval_space_tokens.append(item.get("eval_data", {}).get("space_token"))
                evals_map = {item["linked_handle"]: item for item in evals_map}
                space_infos = Space.objects.filter(token__in=eval_space_tokens).values('token', "slug")
                space_info_map = {item["token"]: item for item in space_infos}

            private_thread_space = {}
            public_threads_space = {}
            org_dict = {}
            for org in org_obj:
                org_dict[org.id] = SpaceOrganizationSerializers(org).data

            for t in private_threads:
                if t["post__space_id"] in private_thread_space:
                    continue
                private_thread_space[t["post__space_id"]] = t["post__slug"]
            for t in public_threads:
                if t["space_id"] in public_threads_space:
                    continue
                public_threads_space[t["space_id"]] = t["slug"]
            space_list = space_list.values(
                *SPACE_LIST_ALL,
                "unread_count",
                "total_post",
                "id",
                "space_organization_id",
                "content_type",
            )
            for space in space_list:
                space["is_owner"] = space.pop("created_by", None) == request.user.id
                space["unread_count"] = max(space["unread_count"], 0)
                space_id = space.pop("id")
                space_organization_id = space.pop("space_organization_id")
                space["organization"] = org_dict.get(space_organization_id, {})
                space["private_main_post_slug"] = private_thread_space.get(
                    space_id, None
                )
                space["public_main_post_slug"] = public_threads_space.get(
                    space_id, None
                )
                space["last_main_post_slug"] = get_last_thread(
                    space["private_main_post_slug"], space["public_main_post_slug"]
                )
                if space_type == "knowledge_base":
                    space["has_evals"] = space.get("token") in evals_map
                    if space["has_evals"]:
                      evals_info = evals_map.get(space.get("token"), {})
                      eval_data = evals_info.pop("eval_data", {})
                      evals_info["eval_token"] = eval_data.get("space_token")
                      sp_evals_info = space_info_map.get(evals_info["eval_token"], {})
                      evals_info["eval_slug"] = sp_evals_info.get("slug")
                      space["evals_info"] = evals_info
            # if len(space_list):
            #     space_list.insert(0, getAllSpaceObject())

        else:
            space_list = space_querset.select_related("space_organization").order_by(
                "-id"
            )
            space_list = UnpodCustomPagination(
                self.request, space_list, SpaceListSerializers
            )
            space_list = space_list.get_paginated_response(return_dict=True)
            space_count = space_list["count"]
            space_list = space_list["data"]
            for space in space_list:
                space["is_owner"] = space.pop("created_by", None) == request.user.id
        return Response(
            {
                "data": space_list,
                "count": space_count,
                "message": "Space List Fetch Successfully",
            },
            status=200,
        )

    def space_detail(self, request, *args, **kwargs):
        space_slug = kwargs.get("space_slug")
        space_obj = (
            Space.objects.filter(slug=space_slug, status="active")
            .select_related("space_organization")
            .prefetch_related(
                "spacememberroles_space",
                "spaceinvite_space",
                "spaceaccessrequest_space",
            )
            .first()
        )
        if not space_obj:
            return Response({"message": "Invalid Space Token"}, status=206)
        try:
            checkSpaceAccess(request.user, space_obj)
        except APIException206 as ex:
            if str(ex.detail.get("message")) == "You Don't have Access to this Space":
                cond = {"user_email": request.user.email, "space_id": space_obj.id}
                invitation_data = get_space_invitation_data(cond=cond)
                res = {**ex.detail}
                common_data = {
                    "slug": space_slug,
                    "name": space_obj.name,
                    "token": space_obj.token,
                    "privacy_type": space_obj.privacy_type,
                    "space_type": space_obj.space_type,
                    "subscribed": False,
                    "final_role": DEFAULT_SPACE_PERMISSION_ROLE,
                }
                if len(invitation_data):
                    res.update(
                        {
                            "data": {
                                **invitation_data[0],
                                **common_data,
                                "is_invited": True,
                            }
                        }
                    )
                else:
                    check_request = SpaceAccessRequest.objects.filter(
                        space=space_obj,
                        user=request.user,
                        is_joined=False,
                        is_expired=False,
                    ).first()
                    res.update({"data": {**common_data, "is_invited": False}})
                    res.update({"is_requested": check_request != None, "joined": False})
                    if check_request:
                        res.update({"request_token": check_request.request_token})
                        res.update({"request_role": check_request.role.role_code})
                return Response(res, status=206)
            raise ex
        if request.user.is_authenticated:
            if (
                hasattr(request.user, "userbasicdetail_user")
                and space_obj.space_type == "general"
            ):
                # Use update() instead of save() to avoid lock contention
                UserBasicDetail.objects.filter(user=request.user).update(
                    active_space=space_obj,
                    active_organization=space_obj.space_organization,
                )
        ser = SpaceDetailSerializers(space_obj, context={"request": request}).data
        check_request = SpaceAccessRequest.objects.filter(
            space=space_obj,
            user=request.user,
            is_joined=False,
            is_expired=False,
        ).first()
        if check_request:
            ser["is_requested"] = True
            ser["request_token"] = check_request.request_token

        return Response(
            {"data": ser, "message": "Space Detail Fetch Successfully"}, status=200
        )

    def download_schema(self, request, *args, **kwargs):
        """Download schema for a space - fields are dynamic from DB

        Query params:
            format: csv | excel | json (default: json)
        """
        import csv
        import io
        from django.http import HttpResponse
        from unpod.knowledge_base.models import KnowledgeBaseConfig

        space_slug = kwargs.get("space_slug")
        file_format = request.query_params.get("type", "json").lower()

        space_obj = Space.objects.filter(slug=space_slug).first()

        if not space_obj:
            return Response({"message": "Space not found"}, status=404)

        # Check user access
        space_role = checkSpaceAccess(request.user, space=space_obj, check_role=True)
        checkSpaceOperationAccess(request.user, space_role)

        # Fetch schema dynamically from DB
        try:
            kb_config = KnowledgeBaseConfig.objects.filter(
                knowledge_base=space_obj
            ).first()
            schema = kb_config.schema if kb_config else {}
        except KnowledgeBaseConfig.DoesNotExist:
            schema = {}

        # Get properties from schema (dynamic fields)
        properties = schema.get("properties", None)

        if not properties:
            return Response({"message": "No schema fields found"}, status=404)

        # Extract field names dynamically
        field_names = list(properties.keys())

        if file_format == "excel":
            # Generate Excel
            try:
                from openpyxl import Workbook
            except ImportError:
                return Response({"message": "openpyxl not installed"}, status=500)

            wb = Workbook()
            ws = wb.active
            ws.title = "Schema"

            # Write header row with dynamic fields
            for col, field_name in enumerate(field_names, 1):
                ws.cell(row=1, column=col, value=field_name)

            # Save to bytes
            output = io.BytesIO()
            wb.save(output)
            output.seek(0)

            response = HttpResponse(
                output.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = (
                f'attachment; filename="{space_slug}_schema.xlsx"'
            )
            return response

        else:
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(field_names)  # Header row with dynamic fields

            response = HttpResponse(output.getvalue(), content_type="text/csv")
            response["Content-Disposition"] = (
                f'attachment; filename="{space_slug}_schema.csv"'
            )
            return response

    def update_space(self, request, *args, **kwargs):
        space_slug = kwargs.get("space_slug")
        space_obj = (
            Space.objects.filter(slug=space_slug, status="active")
            .select_related("space_organization")
            .prefetch_related("spacememberroles_space", "spaceinvite_space")
            .first()
        )
        if not space_obj:
            return Response({"message": "Invalid Space Token"}, status=206)
        space_role = checkSpaceAccess(request.user, space=space_obj, check_role=True)
        checkSpaceOperationAccess(request.user, space_role)
        ser = SpaceUpdateSerializers(data=request.data, instance=space_obj)
        check_data = ser.is_valid()
        make_private = False
        if not check_data:
            return Response(
                {"errors": ser.errors, "message": "Required Parameter Missing"},
                status=206,
            )
        privacy_type = ser.validated_data.get("privacy_type")
        if (
            privacy_type
            and privacy_type != "private"
            and space_obj.privacy_type != "private"
        ):
            pass
        elif (
            privacy_type
            and privacy_type == "private"
            and space_obj.privacy_type != "private"
            and space_obj.created_by != request.user.id
        ):
            raise APIException206(
                {
                    "message": "You can't change the privacy to private, As you are not Owner"
                }
            )

        if (
            privacy_type
            and privacy_type == "private"
            and space_obj.privacy_type != "private"
            and space_obj.created_by == request.user.id
        ):
            make_private = True

        file = ser.validated_data.pop("logo", None)
        schema_data = ser.validated_data.pop("schema", {})
        if len(ser.validated_data):
            Space.objects.filter(id=space_obj.id).update(**ser.validated_data)
        if file:
            space_obj.logo = file
            space_obj.save()
        space_obj.refresh_from_db()
        if (
            space_obj.space_type == SpaceType.knowledge_base.name
            or space_obj.content_type != KnowledgeBaseContentType.general.name
        ) and schema_data:
            KnowledgeBaseConfig.objects.update_or_create(
                knowledge_base=space_obj, defaults={"schema": schema_data}
            )
            update_store_schema(space_obj, schema_data)
        if make_private:
            makePostPrivateForSpace(space_obj)
        data = SpaceDetailSerializers(space_obj, context={"request": request}).data
        return Response({"data": data, "message": "Space Updated Successfully"})

    def delete_space(self, request, *args, **kwargs):
        space_slug = kwargs.get("space_slug")
        space_obj = (
            Space.objects.filter(slug=space_slug, status="active")
            .select_related("space_organization")
            .prefetch_related("spacememberroles_space", "spaceinvite_space")
            .first()
        )
        if not space_obj:
            return Response({"message": "Invalid Space Token"}, status=206)
        space_role = checkSpaceAccess(request.user, space=space_obj, check_role=True)
        checkSpaceOperationAccess(request.user, space_role)
        space_obj.delete()
        return Response({"message": "Space Deleted Successfully"})

    def archive_space(self, request, *args, **kwargs):
        space_slug = kwargs.get("space_slug")
        space_obj = (
            Space.objects.filter(slug=space_slug, status="active")
            .prefetch_related("spacememberroles_space")
            .first()
        )
        if not space_obj:
            return Response({"message": "Invalid Space Token"}, status=206)
        space_role = checkSpaceAccess(request.user, space=space_obj, check_role=True)
        if space_role.role.role_code != "owner":
            return Response({"message": "Only owner can archive the Space"}, status=206)
        Space.objects.filter(id=space_obj.id).update(status="archive")
        return Response({"message": "Space archived successfully"}, status=200)

    def get_space_analytics(self, request, *args, **kwargs):
        try:
            space_slug = kwargs.get("space_slug")
            space_obj = Space.objects.filter(slug=space_slug, status="active").first()

            if not space_obj:
                return Response({"message": "Invalid Space Slug"}, status=206)

            space_role = checkSpaceAccess(
                request.user, space=space_obj, check_role=True
            )
            checkSpaceOperationAccess(request.user, space_role)

            analytics = fetch_space_analytics([space_obj.id])  # Pass as array
            if not analytics:
                return Response(
                    {
                        "message": "No analytics data available for this space.",
                        "data": None,
                    },
                    status=200,
                )

            return Response(
                {
                    "data": analytics,
                    "message": "Space analytics fetched successfully",
                },
                status=200,
            )

        except Exception as e:
            return Response(
                {"message": f"An error occurred while fetching analytics: {str(e)}"},
                status=500,
            )


class SpaceInviteViewSet(viewsets.GenericViewSet):
    permission_classes = (AllowAny | IsAuthenticated,)
    serializer_class = CommonSerializer
    renderer_classes = [UnpodJSONRenderer]

    def create(self, request, *args, **kwargs):
        required_fields = ["token", "user_email"]
        validate = Validation(required_fields, request.data)
        if not validate.check_required_fields():
            return Response(
                {
                    "errors": validate.get_error(),
                    "message": "Required Parameter Missing",
                },
                status=206,
            )
        validate.setData()
        input_data = validate.get_data()
        space = Space.objects.filter(token=input_data["token"]).first()
        if not space:
            return Response({"message": "Invalid Space"}, status=206)
        user_email = input_data["user_email"]
        if not len(user_email):
            return Response(
                {"message": "Their should minimum one user email will be provided"},
                status=206,
            )
        success_data, failed_email = processInvitation(space, user_email, request.user)
        return Response(
            {
                "message": "Space Invitation Sent Successfully",
                "failed_invite": failed_email,
                "success_data": success_data,
            },
            status=201,
        )

    def inviteJoin(self, request, *args, **kwargs):
        token = kwargs.get("token")
        invite_obj = SpaceInvite.objects.filter(invite_token=token).first()
        if not invite_obj:
            return Response(
                {"message": "Please provide valid invitation token"}, status=206
            )
        if not invite_obj.invite_verified:
            return Response(
                {"message": "Please verify the invitation before join"}, status=206
            )
        if invite_obj.is_joined:
            return Response(
                {"message": "You are already member of this space"}, status=206
            )
        if invite_obj.expired:
            return Response({"message": "This Invite is Expired"}, status=206)
        user = request.user
        if user.is_anonymous:
            return Response({"message": "Please Login to join the space"}, status=206)
        if user.email != invite_obj.user_email:
            return Response({"message": "Invalid User/Invite Token"}, status=206)
        space_mem = SpaceMemberRoles.objects.filter(
            user=user, space=invite_obj.space
        ).first()
        if space_mem:
            return Response({"message": "You are already member of this space"})
        space_mem = SpaceMemberRoles.objects.create(
            user=user,
            space=invite_obj.space,
            role=invite_obj.role,
            grant_by=invite_obj.invite_by.id,
        )
        org_role = getRole("viewer", "organization")
        org_user_role, created = OrganizationMemberRoles.objects.get_or_create(
            user=user, organization=invite_obj.space.space_organization
        )
        if created:
            org_user_role.role = org_role
            org_user_role.created_by = user.id
            org_user_role.updated_by = user.id
            org_user_role.grant_by = invite_obj.invite_by.id
            org_user_role.save()
        invite_obj.is_joined = True
        invite_obj.joined_dt = timezone.now()
        invite_obj.save()
        if invite_obj.space.privacy_type == "private":
            Space.objects.filter(id=invite_obj.space.id).update(privacy_type="shared")
        expireNotification("space", token)

        name = invite_obj.space.name
        accept_data = {
            "event": "invitation_accepted",
            "object_type": "space",
            "user_from": user.id,
            "user_to": invite_obj.invite_by.id,
            "event_data": {
                "name": invite_obj.space.name,
                "slug": invite_obj.space.slug,
                "token": invite_obj.space.token,
            },
            "title": "Invitation Accepted",
            "body": f"{user.full_name} has accepted your invitation to join the space {name}.",
        }

        createNotification(**accept_data)

        data = SpaceDetailSerializers(
            invite_obj.space, context={"request": request}
        ).data
        return Response(
            {"message": "You Succefully Joined the Space", "data": data}, status=200
        )

    def inviteResend(self, request, *args, **kwargs):
        token = kwargs.get("token")
        invite_obj = SpaceInvite.objects.filter(invite_token=token).first()
        if not invite_obj:
            return Response(
                {"message": "Please provide valid invitation token"}, status=206
            )
        if invite_obj.invite_verified:
            return Response(
                {"message": "Invitation is Already verified by User"}, status=206
            )
        if invite_obj.is_joined:
            return Response({"message": "User Already Joined the Space"}, status=206)
        if invite_obj.expired:
            return Response({"message": "This Invite is Expired"}, status=206)
        user = request.user
        if user.is_anonymous:
            return Response({"message": "Please Login to send invitation"}, status=206)
        redis_key = f"resend_invite_{invite_obj.invite_token}"
        cache_obj = cache.get(redis_key)
        if not cache_obj:
            cache.set(redis_key, json.dumps({"resent": 1}), 600)
        else:
            cache_ttl = cache.ttl(redis_key)
            cache_obj = json.loads(cache_obj)
            if cache_obj.get("resent") >= 3:
                message = (
                    f"Please wait for {cache_ttl} seconds to resent the Invitation"
                )
                return Response({"message": message}, status=206)
            else:
                cache.set(
                    redis_key,
                    json.dumps({"resent": cache_obj.get("resent") + 1}),
                    cache_ttl,
                )
        invite_usable = User(id=None)
        invite_obj.invite_by = invite_obj.invite_by or invite_usable
        sendInviteMail(invite_obj)

        notification = Notification.objects.filter(
            user_to=invite_obj.user_email,
            object_type="space",
            object_id=invite_obj.space.slug,
            event="invitation",
            read=False,
        ).first()

        if notification:
            # Expire previous notification and send new notification
            notification.read = True
            notification.expired = True
            notification.save()

            data = {
                "user_to": notification.user_to,
                "user_from": user.id,
                "object_type": notification.object_type,
                "object_id": notification.object_id,
                "event_data": notification.event_data,
                "event": notification.event,
                "title": notification.title,
                "body": notification.body,
            }
            createNotification(**data)

        return Response({"message": "Invite Successfully Resent"}, status=200)

    def userInvitePending(self, request, *args, **kwargs):
        user_email = request.user.email
        space_invitation_data = get_space_invitation_data(user_email)
        return Response(
            {
                "message": "Pending Invitation Successfully Fetced",
                "data": space_invitation_data,
            },
            status=200,
        )

    def spaceInvitePending(self, request, *args, **kwargs):
        token = kwargs.get("token")
        space_role = checkSpaceAccess(
            request.user, token=token, check_role=True, expired=False
        )
        checkSpaceOperationAccess(request.user, space_role)
        space_invitation_data = get_space_invitation_data(token=token)
        return Response(
            {
                "message": "Space Pending Invitation Successfully Fetced",
                "data": space_invitation_data,
            },
            status=200,
        )

    def deleteInvite(self, request, *args, **kwargs):
        token = kwargs.get("token")
        print("token", token)
        invite_obj = (
            SpaceInvite.objects.filter(
                invite_token=token, is_joined=False, expired=False
            )
            .select_related("space")
            .first()
        )
        print("invite_obj", invite_obj)
        if not invite_obj:
            raise APIException206({"message": "Invalid Invite Token"})
        space_role = checkSpaceAccess(
            request.user, space=invite_obj.space, check_role=True
        )
        checkSpaceOperationAccess(request.user, space_role)
        invite_obj.delete()
        expireNotification("space", token)
        return Response({"message": "Space Invite Removed Successfully"})

    def updateInvite(self, request, *args, **kwargs):
        token = kwargs.get("token")
        invite_obj = (
            SpaceInvite.objects.filter(
                invite_token=token, is_joined=False, expired=False
            )
            .select_related("space")
            .first()
        )
        if not invite_obj:
            raise APIException206({"message": "Invalid Invite Token"})
        space_role = checkSpaceAccess(
            request.user, space=invite_obj.space, check_role=True
        )
        checkSpaceOperationAccess(request.user, space_role)
        ser = SpaceAccessRequestUpdateSerializer(data=request.data)
        if ser.is_valid():
            role = getRole(
                role_code=ser.validated_data.get("role_code"), role_type="space"
            )
            SpaceInvite.objects.filter(id=invite_obj.id).update(role=role)
            return Response({"message": "Space Invite Updated Successfully"})
        return Response(
            {"message": "There is some Validation error", "errors": ser.errors},
            status=206,
        )

    def inviteCancel(self, request, *args, **kwargs):
        token = kwargs.get("token")
        invite_obj = SpaceInvite.objects.filter(
            invite_token=token, is_joined=False
        ).first()
        if not invite_obj:
            raise APIException206({"message": "Invalid Invite Token"})
        if invite_obj.expired:
            return Response({"message": "This Invite is Expired"}, status=206)
        if request.user.email != invite_obj.user_email:
            return Response({"message": "You only cancel your invite"}, status=206)
        SpaceInvite.objects.filter(id=invite_obj.id).update(
            expired=True, expired_dt=timezone.now()
        )
        expireNotification("space", token)
        return Response({"message": "Space Invitation Cancelled"})


class RolesViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = CommonSerializer
    renderer_classes = [UnpodJSONRenderer]

    def list(self, request):
        roles = Roles.objects.filter(role_type="space").values(
            "role_name", "role_code", "is_default"
        )
        return Response(
            {"data": roles, "message": "Roles Fetch Successfully"}, status=200
        )

    def createInvite(self, request, *args, **kwargs):
        token = kwargs.get("token")
        space_role = checkSpaceAccess(request.user, token=token, check_role=True)
        checkSpaceOperationAccess(request.user, space_role)
        ser = SpaceRolePermissionCreateSerializer(data=request.data, many=True)
        if ser.is_valid():
            invite_data = ser.validated_data
            success_data, failed_email = processInvitation(
                space_role.space, invite_data, request.user
            )
            return Response(
                {
                    "message": "Space Invitation Sent Successfully",
                    "data": {
                        "failed_invite": failed_email,
                        "success_data": success_data,
                    },
                },
                status=201,
            )
        return Response({"message": format_validation_errors(ser.errors)}, status=206)

    def permission_update(self, request, *args, **kwargs):
        token = kwargs.get("token")
        space_role = checkSpaceAccess(request.user, token=token, check_role=True)
        checkSpaceOperationAccess(request.user, space_role)
        ser = SpaceRolePermissionCreateSerializer(data=request.data)
        if ser.is_valid():
            validated_data = ser.validated_data
            user_email = validated_data["email"]
            if user_email == request.user.email:
                raise APIException206(
                    {"message": "You Can't Update the Permission of Self"}
                )
            processUpdatePermission(
                SpaceMemberRoles,
                validated_data["role_code"],
                validated_data["email"],
                space=space_role.space,
            )
            return Response(
                {
                    "message": "Space Permission Updated Successfully",
                    "data": validated_data,
                },
                status=200,
            )
        return Response(
            {"errors": ser.errors, "message": "Required Parameter Missing"}, status=206
        )

    def permission_delete(self, request, *args, **kwargs):
        token = kwargs.get("token")
        space_role = checkSpaceAccess(request.user, token=token, check_role=True)
        checkSpaceOperationAccess(request.user, space_role)
        user_email = request.GET.get("email")
        user_email = urllib.parse.quote_plus(user_email).replace("%40", "@")
        if not user_email:
            raise APIException206({"message": "Please Provide the Email"})
        if user_email == request.user.email:
            raise APIException206(
                {"message": "You Can't Delete the Permission of Self"}
            )
        processDeletePermission(
            SpaceMemberRoles,
            user_email,
            space=space_role.space,
        )
        return Response({"message": "Space Permission Delete Successfully"}, status=200)

    def ownership_transfer(self, request, *args, **kwargs):
        token = kwargs.get("token")
        space_role = checkSpaceAccess(request.user, token=token, check_role=True)
        checkSpaceOperationAccess(request.user, space_role)
        if space_role.role.role_code != "owner":
            raise APIException206(
                {
                    "message": "You must have the permission of owner to transfer the ownership"
                }
            )
        user_email = request.GET.get("email")
        if not user_email:
            raise APIException206({"message": "Please Provide the Email"})
        # user_email = urllib.parse.quote_plus(user_email).replace("%40", "@")
        if user_email == request.user.email:
            raise APIException206(
                {"message": "You Can't Update the Permission of Self"}
            )
        processUpdatePermission(
            SpaceMemberRoles,
            "owner",
            user_email,
            space=space_role.space,
        )
        redis_key = f"user_roles_{user_email}_space_{space_role.space.id}"
        role = getRole("editor", "space")
        space_role.role = role
        space_role.save()
        space_role.refresh_from_db()
        cache.delete(redis_key)
        return Response(
            {"message": "Space Permission Updated Successfully"}, status=200
        )


class SpaceAccessRequestViewSet(viewsets.GenericViewSet):
    permission_classes = [
        IsAuthenticated,
    ]
    serializer_class = CommonSerializer
    renderer_classes = [UnpodJSONRenderer]

    def request_add(self, request, *args, **kwargs):
        space_slug = kwargs.get("space_slug")
        space = checkSpaceSlug(space_slug)
        if space.privacy_type == "private":
            return Response(
                {"message": "You can't Request to Private Space"}, status=206
            )
        if request.user.is_authenticated:
            access_request = AccessRequestService(request, space, "space")
            check_request = access_request.create_access_request()
            return Response(
                {
                    "message": "Space access request sent Successfully",
                    "data": {"request_token": check_request.request_token},
                }
            )
        return Response({"message": "Please first login to request access"}, status=206)

    def request_accept(self, request, *args, **kwargs):
        space_slug = kwargs.get("space_slug")
        space = checkSpaceSlug(space_slug)
        space_role = checkSpaceAccess(request.user, space=space, check_role=True)
        checkSpaceOperationAccess(request.user, space_role)
        request_token = kwargs.get("request_token")
        access_request = AccessRequestService(request, space, "space")
        success_data = access_request.accept_access_request(request_token)
        return Response(
            {"message": "Space Permission Granted", "data": success_data}, status=200
        )

    def request_update(self, request, *args, **kwargs):
        space_slug = kwargs.get("space_slug")
        space = checkSpaceSlug(space_slug)
        request_token = kwargs.get("request_token")
        access_request = AccessRequestService(request, space, "space")
        access_request.update_access_request(request_token)
        return Response({"message": "Space access request updated Successfully"})

    def request_delete(self, request, *args, **kwargs):
        space_slug = kwargs.get("space_slug")
        space = checkSpaceSlug(space_slug)
        request_token = kwargs.get("request_token")
        access_request = AccessRequestService(request, space, "space")
        access_request.delete_access_request(request_token)
        return Response({"message": "Space access request deleted Successfully"})

    def request_reject(self, request, *args, **kwargs):
        space_slug = kwargs.get("space_slug")
        space = checkSpaceSlug(space_slug)
        space_role = checkSpaceAccess(request.user, space=space, check_role=True)
        checkSpaceOperationAccess(request.user, space_role)
        request_token = kwargs.get("request_token")
        access_request = AccessRequestService(request, space, "space")
        access_request.reject_access_request(request_token)
        return Response({"message": "Space access request rejected Successfully"})

    def request_resend(self, request, *args, **kwargs):
        space_slug = kwargs.get("space_slug")
        space = checkSpaceSlug(space_slug)
        request_token = kwargs.get("request_token")
        if request.user.is_authenticated:
            access_request = AccessRequestService(request, space, "space")
            check_request = access_request.resend_access_request(request_token)
            return Response(
                {
                    "message": "Space access request resent Successfully",
                    "data": {"request_token": check_request.request_token},
                }
            )
        return Response({"message": "Please first login to request access"}, status=206)

    def request_change_role(self, request, *args, **kwargs):
        space_slug = kwargs.get("space_slug")
        space = checkSpaceSlug(space_slug)
        space_role = checkSpaceAccess(request.user, space=space, check_role=True)
        checkSpaceMemberAccess(request.user, space_role)
        new_role_code = request.data.get("role_code")
        if not new_role_code:
            return Response({"message": "Please provide the new role_code"}, status=206)

        access_request = AccessRequestService(request, space, "space")
        check_request = access_request.create_change_role_request(new_role_code)
        return Response(
            {
                "message": "Space role change request sent Successfully",
                "data": {"request_token": check_request.request_token},
            },
            status=200,
        )

    def accept_change_role_request(self, request, *args, **kwargs):
        space_slug = kwargs.get("space_slug")
        space = checkSpaceSlug(space_slug)
        space_role = checkSpaceAccess(request.user, space=space, check_role=True)
        checkSpaceOperationAccess(request.user, space_role)
        request_token = kwargs.get("request_token")
        access_request = AccessRequestService(request, space, "space")
        success_data = access_request.accept_change_role_request(request_token)
        return Response(
            {"message": "Space role changed Successfully", "data": success_data},
            status=200,
        )


class SubscribeViewSet(viewsets.GenericViewSet):
    permission_classes = (IsAuthenticatedOrReadOnly,)
    serializer_class = CommonSerializer
    renderer_classes = [UnpodJSONRenderer]

    def get_trending(self, request, *args, **kwargs):
        role_space_id = []
        if request.user.is_authenticated:
            email = request.user.email
            domain = fetch_email_domain(email)
            is_private_domain = validate_email_type(email)
            role_space_id = SpaceMemberRoles.objects.filter(
                user=request.user
            ).values_list("space_id", flat=True)
            role_space_id = list(role_space_id)
            if is_private_domain:
                org = SpaceOrganization.objects.filter(
                    is_private_domain=True, domain=domain
                ).first()
                if org:
                    space_list = Space.objects.filter(
                        ~Q(id__in=role_space_id),
                        space_organization=org,
                        privacy_type="public",
                        is_default=False,
                        space_type=SpaceType.general.name,
                    ).values(
                        "name", "token", "privacy_type", "slug", "space_organization_id"
                    )
                    if space_list:
                        space_list = add_org(space_list)
                        return Response({"data": space_list})
        order_list = ["name", "token", "id"]
        order_by = random.choice(order_list)
        space_list = (
            Space.objects.filter(
                ~Q(id__in=role_space_id),
                privacy_type="public",
                is_default=False,
                space_type=SpaceType.general.name,
            )
            .order_by(f"-{order_by}")
            .values("name", "token", "privacy_type", "slug", "space_organization_id")[
                :5
            ]
        )
        random.shuffle(list(space_list))
        space_list = add_org(space_list)
        return Response({"data": space_list})

    def join_subscribe(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return Response({"message": "Please First Login"}, status=206)
        space_slug = kwargs.get("space_slug")
        space = checkSpaceSlug(space_slug)
        check_access = SpaceMemberRoles.objects.filter(
            user=request.user, space=space
        ).first()
        if check_access:
            return Response(
                {"message": "You are already member of this space"}, status=206
            )
        if space.privacy_type != "public":
            return Response(
                {"message": "You Only Subscribe to public Space"}, status=206
            )
        role = getRole(role_code="viewer", role_type="space")
        obj = SpaceMemberRoles.objects.create(
            space_id=space.id,
            role_id=role.id,
            user_id=request.user.id,
            grant_by=request.user.id,
        )
        org_role = getRole("viewer", "organization")
        org_user_role, created = OrganizationMemberRoles.objects.get_or_create(
            user=request.user, organization=space.space_organization
        )
        if created:
            org_user_role.role = org_role
            org_user_role.created_by = request.user.id
            org_user_role.updated_by = request.user.id
            org_user_role.grant_by = request.user.id
            org_user_role.save()
        data = SpaceDetailSerializers(space, context={"request": request}).data
        return Response({"message": "You subscribed the space", "data": data})

    def leave_subscribe(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return Response({"message": "Please First Login"}, status=206)
        space_slug = kwargs.get("space_slug")
        space = checkSpaceSlug(space_slug)
        check_access = SpaceMemberRoles.objects.filter(
            user=request.user, space=space
        ).first()
        if not check_access:
            return Response({"message": "You are not member of this space"}, status=206)

        deleted = processDeletePermission(
            SpaceMemberRoles,
            request.user.email,
            space=check_access.space,
        )

        if deleted:
            # Expire space related user access requests
            SpaceAccessRequest.objects.filter(
                space=space, user=request.user, is_joined=False, is_expired=False
            ).update(is_expired=True)

        return Response({"message": f"You left {space.name} Space"}, status=200)


class OrganizationPermissionViewSet(viewsets.GenericViewSet):
    permission_classes = (IsAuthenticated,)
    serializer_class = CommonSerializer
    renderer_classes = [UnpodJSONRenderer]

    def join(self, request, *args, **kwargs):
        token = kwargs.get("token")
        data = checkJoinOrgInvite(token, request.user)
        expireNotification("organization", token)
        return Response(
            {"message": "You Successfully Joined the Organization", "data": data},
            status=200,
        )

    def permission_update(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        org = checkSpaceOrg(domain_handle)
        org_role = checkOrgAccess(request.user, org, check_role=True)
        checkOrgOperationAccess(request.user, org_role)
        serializer = SpaceRolePermissionCreateSerializer(data=request.data)
        if serializer.is_valid():
            validated_data = serializer.validated_data
            user_email = validated_data["email"]
            if user_email == request.user.email:
                raise APIException206(
                    {"message": "You Can't Update the Permission of Self"}
                )
            processUpdatePermission(
                OrganizationMemberRoles,
                validated_data["role_code"],
                validated_data["email"],
                org=org_role.organization,
            )
            return Response(
                {
                    "message": "Organization Permission Updated Successfully",
                    "data": validated_data,
                },
                status=200,
            )
        return Response(
            {"errors": serializer.errors, "message": "Required Parameter Missing"},
            status=206,
        )

    def permission_delete(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        org = checkSpaceOrg(domain_handle)
        org_role = checkOrgAccess(request.user, org, check_role=True)
        checkOrgOperationAccess(request.user, org_role)
        user_email = request.GET.get("email")
        user_email = urllib.parse.quote_plus(user_email).replace("%40", "@")
        if not user_email:
            raise APIException206({"message": "Please Provide the Email"})
        if user_email == request.user.email:
            raise APIException206(
                {"message": "You Can't Delete the Permission of Self"}
            )
        processDeletePermission(
            OrganizationMemberRoles,
            user_email,
            org=org_role.organization,
        )
        return Response(
            {"message": "Organization Permission Delete Successfully"}, status=200
        )

    def ownership_transfer(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        org = checkSpaceOrg(domain_handle)
        org_role = checkOrgAccess(request.user, org, check_role=True)
        checkOrgOperationAccess(request.user, org_role)
        if org_role.role.role_code != "owner":
            raise APIException206(
                {
                    "message": "You must have the permission of owner to transfer the ownership"
                }
            )
        user_email = request.GET.get("email")
        if not user_email:
            raise APIException206({"message": "Please Provide the Email"})
        # user_email = urllib.parse.quote_plus(user_email).replace("%40", "@")
        if user_email == request.user.email:
            raise APIException206(
                {"message": "You Can't Update the Permission of Self"}
            )
        processUpdatePermission(
            OrganizationMemberRoles,
            "owner",
            user_email,
            org=org_role.organization,
        )
        redis_key = f"user_roles_{user_email}_organization_{org.id}"
        role = getRole("editor", "organization")
        org_role.role = role
        org_role.save()
        org_role.refresh_from_db()
        cache.delete(redis_key)

        return Response(
            {"message": "Organization Permission Updated Successfully"}, status=200
        )

    def createInvite(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        org = checkSpaceOrg(domain_handle)
        org_role = checkOrgAccess(request.user, org, check_role=True)
        checkOrgOperationAccess(request.user, org_role)
        serializer = SpaceRolePermissionCreateSerializer(data=request.data, many=True)
        if serializer.is_valid():
            invite_data = serializer.validated_data
            success_data, failed_email = processInvitation(
                org_role.organization,
                invite_data,
                request.user,
                invite_type="organization",
            )
            return Response(
                {
                    "message": "Organization Invitation Sent Successfully",
                    "data": {
                        "failed_invite": failed_email,
                        "success_data": success_data,
                    },
                },
                status=201,
            )
        return Response(
            {"errors": serializer.errors, "message": "Required Parameter Missing"},
            status=206,
        )

    def deleteInvite(self, request, *args, **kwargs):
        token = kwargs.get("token")
        invite_obj = (
            OrganizationInvite.objects.filter(
                invite_token=token, is_joined=False, expired=False
            )
            .select_related("organization")
            .first()
        )
        if not invite_obj:
            raise APIException206({"message": "Invalid Invite Token"})
        org_role = checkOrgAccess(
            request.user, invite_obj.organization, check_role=True
        )
        checkOrgOperationAccess(request.user, org_role)
        invite_obj.delete()
        expireNotification("organization", token)
        return Response({"message": "Organization Invite Removed Successfully"})

    def updateInvite(self, request, *args, **kwargs):
        token = kwargs.get("token")
        invite_obj = (
            OrganizationInvite.objects.filter(
                invite_token=token, is_joined=False, expired=False
            )
            .select_related("organization")
            .first()
        )
        if not invite_obj:
            raise APIException206({"message": "Invalid Invite Token"})
        org_role = checkOrgAccess(
            request.user, invite_obj.organization, check_role=True
        )
        checkOrgOperationAccess(request.user, org_role)
        ser = SpaceAccessRequestUpdateSerializer(data=request.data)
        if ser.is_valid():
            role = getRole(
                role_code=ser.validated_data.get("role_code"), role_type="organization"
            )
            OrganizationInvite.objects.filter(id=invite_obj.id).update(role=role)

            return Response({"message": "Organization Invite Updated Successfully"})
        return Response(
            {"message": "There is some Validation error", "errors": ser.errors},
            status=206,
        )

    def inviteResend(self, request, *args, **kwargs):
        token = kwargs.get("token")
        invite_obj = OrganizationInvite.objects.filter(invite_token=token).first()
        if not invite_obj:
            return Response(
                {"message": "Please provide valid invitation token"}, status=206
            )
        if invite_obj.invite_verified:
            return Response(
                {"message": "Invitation is Already verified by User"}, status=206
            )
        if invite_obj.is_joined:
            return Response(
                {"message": "User Already Joined the organization"}, status=206
            )
        if invite_obj.expired:
            return Response({"message": "This Invite is Expired"}, status=206)
        user = request.user
        if user.is_anonymous:
            return Response({"message": "Please Login to send invitation"}, status=206)
        redis_key = f"resend_invite__hub_{invite_obj.invite_token}"
        cache_obj = cache.get(redis_key)
        if not cache_obj:
            cache.set(redis_key, json.dumps({"resent": 1}), 600)
        else:
            cache_ttl = cache.ttl(redis_key)
            cache_obj = json.loads(cache_obj)
            if cache_obj.get("resent") >= 3:
                message = (
                    f"Please wait for {cache_ttl} seconds to resent the Invitation"
                )
                return Response({"message": message}, status=206)
            else:
                cache.set(
                    redis_key,
                    json.dumps({"resent": cache_obj.get("resent") + 1}),
                    cache_ttl,
                )
        sendInviteMail(invite_obj, invite_type="organization")
        notification = Notification.objects.filter(
            user_to=invite_obj.user_email,
            object_type="organization",
            object_id=invite_obj.organization.domain_handle,
            event="invitation",
            read=False,
        ).first()

        if notification:
            # Expire previous notification and send new notification
            notification.read = True
            notification.expired = True
            notification.save()

            data = {
                "user_to": notification.user_to,
                "user_from": user.id,
                "object_type": notification.object_type,
                "object_id": notification.object_id,
                "event_data": notification.event_data,
                "event": notification.event,
                "title": notification.title,
                "body": notification.body,
            }
            createNotification(**data)

        return Response({"message": "Invite Successfully Resent"}, status=200)

    def subscribe_my_organization(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        org = checkSpaceOrg(domain_handle)
        check_access = OrganizationMemberRoles.objects.filter(
            user=request.user, organization=org
        ).first()

        if check_access:
            return Response(
                {"message": "You are already member of this organization"}, status=206
            )

        return self.subscribe(request, org=org)

    def subscribe_join(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        org = checkSpaceOrg(domain_handle)
        check_access = OrganizationMemberRoles.objects.filter(
            user=request.user, organization=org
        ).first()

        if check_access:
            return Response(
                {"message": "You are already member of this Organization"}, status=206
            )
        if org.privacy_type != "public":
            return Response(
                {"message": "You Only Subscribe to public Organization"}, status=206
            )

        return self.subscribe(request, org=org)

    def subscribe(self, request, org=None):
        invite_obj = OrganizationInvite.objects.filter(
            user_email=request.user.email,
            organization=org,
            is_joined=False,
            expired=False,
        ).last()

        user = request.user

        if invite_obj:
            data = checkJoinOrgInvite(
                invite_obj.invite_token, request.user, check_verify=False
            )
            expireNotification("organization", invite_obj.invite_token)

            name = invite_obj.organization.name
            accept_data = {
                "event": "invitation_accepted",
                "object_type": "organization",
                "user_from": user.id,
                "user_to": invite_obj.invite_by.id,
                "event_data": {
                    "name": invite_obj.organization.name,
                    "domain_handle": invite_obj.organization.domain_handle,
                },
                "title": "Invitation Accepted",
                "body": f"{user.full_name} has accepted your invitation to join the organization {name}.",
            }
            createNotification(**accept_data)

            return Response(
                {
                    "message": "You successfully subscribed to the Organization",
                    "data": data,
                }
            )

        role = getRole(role_code="viewer", role_type="organization")
        OrganizationMemberRoles.objects.create(
            organization_id=org.id,
            role_id=role.id,
            user_id=request.user.id,
            grant_by=request.user.id,
        )
        data = SpaceOrgDetailSerializers(org, context={"request": request}).data
        return Response(
            {"message": "You successfully subscribed to the Organization", "data": data}
        )

    def subscribe_leave(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return Response({"message": "Please First Login"}, status=206)
        domain_handle = kwargs.get("domain_handle")
        org = checkSpaceOrg(domain_handle)
        check_access = OrganizationMemberRoles.objects.filter(
            user=request.user, organization=org
        ).first()
        if not check_access:
            return Response(
                {"message": "You are not member of this organization"}, status=206
            )
        deleted = processDeletePermission(
            OrganizationMemberRoles,
            request.user.email,
            org=check_access.organization,
        )

        if deleted:
            # Expire organization related user access requests
            OrganizationAccessRequest.objects.filter(
                organization=org,
                user=request.user,
                is_joined=False,
                is_expired=False,
            ).update(is_expired=True)

        return Response({"message": f"You left {org.name} organization"}, status=200)

    def fetch_user_list(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        org = checkSpaceOrg(domain_handle)
        search = self.request.GET.get("search")
        query = {"organization_id": org.id}
        if search and search != "":
            search = urllib.parse.quote_plus(search).replace("%40", "@")
            query.update({"user__email__icontains": search})
        user_list = (
            OrganizationMemberRoles.objects.filter(**query)
            .select_related("user")
            .values("user__email", "user__first_name", "user__last_name")
        )
        for user in user_list:
            user["user_email"] = user.pop("user__email", "")
            user["full_name"] = get_name(
                user.pop("user__first_name", ""), user.pop("user__last_name", "")
            )
        return Response({"message": "User List", "data": user_list})


class OrganizationAccessRequestViewSet(viewsets.GenericViewSet):
    permission_classes = [
        IsAuthenticated,
    ]
    serializer_class = CommonSerializer
    renderer_classes = [UnpodJSONRenderer]

    def request_add(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        org = checkSpaceOrg(domain_handle)
        if request.user.is_authenticated:
            access_request = AccessRequestService(request, org, "organization")
            check_request = access_request.create_access_request()
            return Response(
                {
                    "message": "Organization access request sent Successfully",
                    "data": {"request_token": check_request.request_token},
                }
            )
        return Response({"message": "Please first login to request access"}, status=206)

    def request_accept(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        org = checkSpaceOrg(domain_handle)
        org_role = checkOrgAccess(request.user, org, check_role=True)
        checkOrgOperationAccess(request.user, org_role)
        request_token = kwargs.get("request_token")
        access_request = AccessRequestService(request, org, "organization")
        success_data = access_request.accept_access_request(request_token)

        return Response(
            {"message": "Organization Permission Granted", "data": success_data},
            status=200,
        )

    def request_update(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        org = checkSpaceOrg(domain_handle)
        request_token = kwargs.get("request_token")
        access_request = AccessRequestService(request, org, "organization")
        access_request.update_access_request(request_token)
        return Response({"message": "Organization access request updated Successfully"})

    def request_delete(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        org = checkSpaceOrg(domain_handle)
        request_token = kwargs.get("request_token")
        access_request = AccessRequestService(request, org, "organization")
        access_request.delete_access_request(request_token)
        return Response({"message": "Organization access request deleted Successfully"})

    def request_reject(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        org = checkSpaceOrg(domain_handle)
        org_role = checkOrgAccess(request.user, org, check_role=True)
        checkOrgOperationAccess(request.user, org_role)
        request_token = kwargs.get("request_token")
        access_request = AccessRequestService(request, org, "organization")
        access_request.reject_access_request(request_token)
        return Response(
            {"message": "Organization access request rejected Successfully"}
        )

    def request_resend(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        org = checkSpaceOrg(domain_handle)
        request_token = kwargs.get("request_token")
        if request.user.is_authenticated:
            access_request = AccessRequestService(request, org, "organization")
            check_request = access_request.resend_access_request(request_token)
            return Response(
                {
                    "message": "Organization access request resent Successfully",
                    "data": {"request_token": check_request.request_token},
                }
            )
        return Response({"message": "Please first login to request access"}, status=206)

    def request_change_role(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        org = checkSpaceOrg(domain_handle)
        if request.user.is_authenticated:
            org_role = checkOrgAccess(request.user, org, check_role=True)
            checkOrgMemberAccess(request.user, org_role)
            ser = SpaceAccessRequestUpdateSerializer(data=request.data)
            if ser.is_valid():
                access_request = AccessRequestService(request, org, "organization")
                role_code = ser.validated_data.get("role_code")
                access_request.create_change_role_request(role_code)
                return Response(
                    {"message": "Organization role change request sent Successfully"}
                )
            return Response(
                {"message": "There is some Validation error", "errors": ser.errors},
                status=206,
            )
        return Response({"message": "Please first login to request access"}, status=206)

    def accept_change_role_request(self, request, *args, **kwargs):
        domain_handle = kwargs.get("domain_handle")
        org = checkSpaceOrg(domain_handle)
        org_role = checkOrgAccess(request.user, org, check_role=True)
        checkOrgOperationAccess(request.user, org_role)
        request_token = kwargs.get("request_token")
        access_request = AccessRequestService(request, org, "organization")
        success_data = access_request.accept_change_role_request(request_token)
        return Response(
            {"message": "Organization role changed Successfully", "data": success_data},
            status=200,
        )


class OrganizationBillingInfoViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = BillingInfoRetrieveSerializer
    renderer_classes = [UnpodJSONRenderer]
    lookup_field = "pk"

    def get_organization(self):
        """Get organization from domain_handle in URL."""
        domain_handle = self.kwargs.get("domain_handle")
        try:
            return SpaceOrganization.objects.get(domain_handle=domain_handle)
        except SpaceOrganization.DoesNotExist:
            raise Http404("Organization not found")

    def get_queryset(self):
        organization = self.get_organization()
        return SpaceOrganizationBillingInfo.objects.filter(organization=organization)

    def retrieve(self, request, *args, **kwargs):
        try:
            billing_info = self.get_queryset().filter(default=True).first()

            if not billing_info:
                organization = self.get_organization()
                billing_info = SpaceOrganizationBillingInfo.objects.create(
                    organization=organization,
                    default=True,
                )

            serializer = self.get_serializer(billing_info)

            return Response(
                {
                    "data": serializer.data,
                    "message": "Billing information retrieved successfully",
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            return Response(
                {
                    "status_code": 400,
                    "message": "Failed to fetch data.",
                    "error": str(e),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    def update(self, request, *args, **kwargs):
        try:
            organization = self.get_organization()
            billing_info = self.get_queryset().filter(default=True).first()
        except SpaceOrganizationBillingInfo.DoesNotExist:
            return Response({"message": "Billing information not found"}, status=404)

        serializer = BillingInfoSerializer(
            billing_info, data=request.data, partial=True
        )

        if not serializer.is_valid():
            return Response(
                {"errors": serializer.errors, "message": "Validation failed"},
                status=status.HTTP_206_PARTIAL_CONTENT,
            )

        # Check if user has permission to manage billing info for this organization
        user = request.user
        org_role = checkOrgAccess(user, organization, check_role=True)
        checkOrgOperationAccess(user, org_role)

        serializer.save()
        serializer = self.get_serializer(billing_info)

        return Response(
            {
                "data": serializer.data,
                "message": "Billing information updated successfully",
            },
            status=status.HTTP_200_OK,
        )

class SpaceMongoDBViewSet(viewsets.GenericViewSet):
    queryset = Space.objects.all()
    serializer_class = CommonSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'slug'

    @staticmethod
    def get_calls(request, *args, **kwargs):
        try:
            space_slug = kwargs.get("space_slug")
            space = checkSpaceSlug(space_slug)
            space_role = checkSpaceAccess(request.user, space=space, check_role=True)
            checkSpaceOperationAccess(request.user, space_role)

            total_count, data = get_calls(space.id, request.query_params.dict())

            return Response(
                {
                    "data": data,
                    "count": total_count,
                    "message": "Space calls fetched successfully",
                },
                status=200,
            )

        except Exception as e:
            return Response(
                {"message": f"An error occurred while fetching calls: {str(e)}"},
                status=500,
            )

    @staticmethod
    def get_call_details(request, *args, **kwargs):
        try:
            space_slug = kwargs.get("space_slug")
            space = checkSpaceSlug(space_slug)
            space_role = checkSpaceAccess(request.user, space=space, check_role=True)
            checkSpaceOperationAccess(request.user, space_role)

            data = get_task_details(kwargs.get("task_id"))
            if not data:
                return Response({"message": "Data not found"}, status=404)

            pilot = Pilot.objects.filter(handle=data.get("assignee")).values('name').first()
            data["assignee_name"] = pilot.get("name") if pilot else None

            return Response(
                {
                    "data": data,
                    "message": "Call details fetched successfully",
                },
                status=200,
            )
        except Exception as e:
            return Response(
                {"message": f"An error occurred while fetching task details: {str(e)}"},
                status=500,
            )
