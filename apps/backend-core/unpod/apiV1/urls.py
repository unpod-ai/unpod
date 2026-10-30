from django.urls import include, path

# fmt: off
urlpatterns = [
    path('', include('unpod.users.urls'), name="users_v1"),
    path('', include('unpod.core_components.urls'), name="core_components_v1"),
    path('organization/', include('unpod.space.org_urls'), name="space_organization_v1"),
    path('spaces/', include('unpod.space.urls'), name="space_v1"),
    path('threads/', include('unpod.thread.urls'), name="thread_v1"),
    path('roles/', include('unpod.roles.urls'), name="roles_v1"),
    path('notifications/', include('unpod.notification.urls'), name="notification_v1"),
    path('knowledge_base/', include('unpod.knowledge_base.urls'), name="knowledge_base_v1"),
    path('tasks/', include('unpod.core_components.tasks.urls')),
    path('documents/', include('unpod.documents.urls'), name="documents"),
    path('metrics/', include('unpod.metrics.urls'), name="metrics"),
    path('dynamic-forms/', include('unpod.dynamic_forms.urls'), name="dynamic_forms_base"),
    path('email-journey/', include('unpod.email_journey.urls'), name="email_journey"),
]
