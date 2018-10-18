from django.conf.urls import include, url
from django.contrib.auth import views as auth_views

from . import views
from . import component_views

app_name = 'slat'
urlpatterns = [    
    url(r'^accounts/register/$',
        views.SLATRegistrationView.as_view(),
        name='registration_register'),
    url(r'^accounts/', include('registration.backends.simple.urls')),
    url(r'^password_reset/$', auth_views.PasswordResetView.as_view(), name='password_reset'),
    url(r'^password_reset/done/$', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    url(r'^password_change/$', views.password_change, name='password_change'),
    url(r'^reset/(?P<uidb64>[0-9A-Za-z_\-]+)/(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,20})/$',
        auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
     url(r'^reset/done/$', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
    url(r'^$', views.index, name='index'),
    url(r'^project/(?P<project_id>[0-9]+)$', views.project, name='project'),
    url(r'^project/(?P<project_id>[0-9]+)/add_user$', views.project_add_user, name='project_add_user'),
    url(r'^project/(?P<project_id>[0-9]+)/remove_user$', views.project_remove_user, name='project_remove_user'),
    url(r'^project/(?P<project_id>[0-9]+)/add_group$', views.project_add_group, name='project_add_group'),
    url(r'^project/(?P<project_id>[0-9]+)/remove_group$', views.project_remove_group, name='project_remove_group'),
    url(r'^project$', views.project, name='project'),
    url(r'^group/(?P<group_id>[0-9]+)$', views.group, name='group'),
    url(r'^group/(?P<group_id>[0-9]+)/add_user$', views.group_add_user, name='group_add_user'),
    url(r'^group/(?P<group_id>[0-9]+)/remove_user$', views.group_remove_user, name='group_remove_user'),
    url(r'^group$', views.group, name='group'),
    url(r'^components$', component_views.components, name='components'),
    url(r'^components/(?P<component_id>[A-Za-z0-9.]+)$', component_views.component, name='component'),
    url(r'^project/(?P<project_id>[0-9]+)/hazard$', views.hazard, name='hazard'),
    url(r'^project/(?P<project_id>[0-9]+)/hazard/choose$', views.hazard_choose, name='hazard_choose'),
    url(r'^project/(?P<project_id>[0-9]+)/hazard/nlh$', views.nlh, name='nlh'),
    url(r'^project/(?P<project_id>[0-9]+)/hazard/nlh/edit$', views.nlh_edit, name='nlh_edit'),
    url(r'^project/(?P<project_id>[0-9]+)/hazard/interp$', views.im_interp, name='im_interp'),
    url(r'^project/(?P<project_id>[0-9]+)/hazard/interp/edit$', views.im_interp_edit, name='im_interp_edit'),
    url(r'^project/(?P<project_id>[0-9]+)/hazard/interp/import$', views.im_file, name='im_file'),
    url(r'^project/(?P<project_id>[0-9]+)/hazard/nzs$', views.im_nzs, name='nzs'),
    url(r'^project/(?P<project_id>[0-9]+)/hazard/nzs/edit$', views.im_nzs_edit, name='im_nzs_edit'),
    url(r'^project/(?P<project_id>[0-9]+)/edp/(?P<edp_id>[0-9]+)$', views.edp_view, name='edp_view'),
    url(r'^project/(?P<project_id>[0-9]+)/edp/init$', views.edp_init, name='edp_init'),
    url(r'^project/(?P<project_id>[0-9]+)/edp/(?P<edp_id>[0-9]+)/choose$', views.edp_choose, name='edp_choose'),
    url(r'^project/(?P<project_id>[0-9]+)/edp/(?P<edp_id>[0-9]+)/power$', views.edp_power, name='edp_power'),
    url(r'^project/(?P<project_id>[0-9]+)/edp/(?P<edp_id>[0-9]+)/power/edit$', views.edp_power_edit, name='edp_power_edit'),
    url(r'^project/(?P<project_id>[0-9]+)/edp/(?P<edp_id>[0-9]+)/userdef$', views.edp_userdef, name='edp_userdef'),
    url(r'^project/(?P<project_id>[0-9]+)/edp/(?P<edp_id>[0-9]+)/userdef/edit$', views.edp_userdef_edit, name='edp_userdef_edit'),
    url(r'^project/(?P<project_id>[0-9]+)/edp/(?P<edp_id>[0-9]+)/userdef/import$', views.edp_userdef_import, name='edp_userdef_import'),
    url(r'^project/(?P<project_id>[0-9]+)/edp/(?P<edp_id>[0-9]+)/cgroups$', views.edp_cgroups, name='edp_cgroups'),
    url(r'^project/(?P<project_id>[0-9]+)/edp/(?P<edp_id>[0-9]+)/cgroup$', views.edp_cgroup, name='edp_cgroup'),
    url(r'^project/(?P<project_id>[0-9]+)/edp/(?P<edp_id>[0-9]+)/cgroup/(?P<cg_id>[0-9]+)$', views.edp_cgroup, name='edp_cgroup'),
    url(r'^project/(?P<project_id>[0-9]+)/cgroups$', views.cgroups, name='compgroups'),
    url(r'^project/(?P<project_id>[0-9]+)/cgroups/(?P<groups>([0-9]+,)*[0-9]+)$', views.cgroups, name='compgroups'),
    url(r'^project/(?P<project_id>[0-9]+)/level/(?P<level_id>[0-9]+)/cgroup$', views.level_cgroup, name='level_compgroup'),
    url(r'^project/(?P<project_id>[0-9]+)/level/(?P<level_id>[0-9]+)/cgroup/(?P<cg_id>[0-9]+)$', views.level_cgroup, name='level_compgroup'),
    url(r'^project/(?P<project_id>[0-9]+)/cgroup$', views.cgroup, name='compgroup'),
    url(r'^project/(?P<project_id>[0-9]+)/cgroup/(?P<cg_id>[0-9]+)$', views.cgroup, name='compgroup'),
    url(r'^project/(?P<project_id>[0-9]+)/cgroup_pattern/(?P<cg_id>[0-9]+)$', views.cgrouppattern, name='compgrouppattern'),
    url(r'^project/(?P<project_id>[0-9]+)/cgroup_pattern$', views.cgrouppattern, name='compgrouppattern'),
    url(r'^project/(?P<project_id>[0-9]+)/analysis$', views.analysis, name='analysis'),
    url(r'^project/(?P<project_id>[0-9]+)/floor_by_floor$', views.floor_by_floor, name='floor_by_floor'),
    url(r'^project/(?P<project_id>[0-9]+)/level/(?P<level_id>[0-9]+)/cgroups$', views.level_cgroups, name='level_cgroups'),
    url(r'^project/(?P<project_id>[0-9]+)/level$', views.levels, name='levels'),
    url(r'^project/(?P<project_id>[0-9]+)/level/(?P<level_id>[0-9]+)/(?P<type>(acceleration)|(drift))/(?P<direction>(X)|(Y))$', views.demand, name='demand'),
    url(r'^project/(?P<project_id>[0-9]+)/shift-level/(?P<level_id>[0-9]+)/(?P<shift>-?[0-9]+)/$', views.shift_level, name='shift_level'),
    url(r'^project/(?P<project_id>[0-9]+)/rename-level/(?P<level_id>[0-9]+)/$', views.rename_level, name='rename_level'),
    url(r'^component-autocomplete/$', views.ComponentAutocomplete.as_view(), name='component-autocomplete'),
    url(r'^component-description/(?P<component_key>[0-9]+)$', views.ComponentDescription, name='component-description'),
    url(r'^etabs_confirm/(?P<preprocess_id>[0-9]+)$', views.etabs_confirm, name='etabs_confirm'),
    url(r'^etabs_progress$', views.etabs_progress,name='etabs_progress'),
    url(r'^celery_poll_state$', views.celery_poll_state,name='celery_poll_state'),
]
