from __future__ import print_function
import sys
import pyslat
import re
import numpy as np
from scipy.optimize import fsolve
from django.http import Http404, HttpResponseRedirect, HttpResponseForbidden, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.forms import modelformset_factory, ValidationError, HiddenInput, RadioSelect
from django.forms.models import model_to_dict
from django.core.exceptions import PermissionDenied
from .nzs import *
from math import *
from dal import autocomplete
from django.template import RequestContext
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.contrib import messages
from django.shortcuts import render, redirect
from  .models import *
from .component_models import *
from slat.constants import *
from django.contrib.auth.decorators import login_required
from django_registration.backends.one_step.views import RegistrationView
from django_registration.forms import RegistrationForm
from django.forms import ModelForm
import sys
from random import randint
from datetime import datetime, timedelta
from django.utils.html import format_html
from jchart import Chart
from jchart.config import Axes, DataSet, rgba, ScaleLabel, Legend, Title
import seaborn as sns
import json
from celery.result import AsyncResult
import celery_tasks
from .tasks import *
from .etabs import ETABS_preprocess
import celery
import tempfile
import os, sys
import logging
from django.template import Context, Template
from django.db.models.signals import pre_delete
import pickle
from django.conf import settings
from django.db.models import Q
from django.db import transaction

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

from django.contrib.auth import REDIRECT_FIELD_NAME
if settings.SINGLE_USER_MODE:
    def login_required(function=None):
        return function
    
@login_required
def index(request):
    project_list = []
    for project in Project.objects.all():
        if project.CanRead(request.user):
            project_list.append({'id': project.id,
                                 'title_text': project.title_text})

    group_list = []
    if request.user != AnonymousUser():
        for group in Group.objects.all():
            if group.IsMember(request.user):
                #group_list.append({'name': group.name})
                group_list.append(group)

                
    context = { 'project_list': project_list, 'group_list': group_list}
    return render(request, 'slat/index.html', context)

@transaction.atomic
def make_demo(user, title, description):
    project = Project()
    setattr(project, 'title_text', title)
    setattr(project, 'description_text', description)
    setattr(project, 'rarity', 1/500)
    project.save()

    project.AssignRole(user, ProjectUserPermissions.ROLE_FULL)

    # Create levels:
    num_floors = 5
    for l in range(num_floors + 1):
        if l == 0:
            label = "Ground Floor"
        elif l == num_floors:
            label = "Roof"
        else:
            label = "Floor #{}".format(l + 1)
        level = Level(project=project, level=l, label=label)
        level.save()
        
    # Create an IM:
    christchurch = Location.objects.get(location='Christchurch')
    nzs = NZ_Standard_Curve(location=christchurch,
                            soil_class = NZ_Standard_Curve.SOIL_CLASS_C,
                            period = 2.0)
    nzs.save()
    hazard = IM(flavour = IM_Types.objects.get(pk=IM_TYPE_NZS), nzs = nzs)
    hazard.save()
    project.IM = hazard
    project.save()

    # Create EDPs:
    demand_params = [
        {'level': 5, 'accel': {'a': 5.39, 'b': 1.5}},
        {'level': 4, 'accel': {'a': 4.18, 'b': 1.5}, 'drift': {'a': 0.0202, 'b': 0.5}},
        {'level': 3, 'accel': {'a': 4.10, 'b': 1.5}, 'drift': {'a': 0.0380, 'b': 0.5}},
        {'level': 2, 'accel': {'a': 4.25, 'b': 1.5}, 'drift': {'a': 0.0506, 'b': 0.5}},
        {'level': 1, 'accel': {'a': 4.15, 'b': 1.5}, 'drift': {'a': 0.0633, 'b': 0.5}},
        {'level': 0, 'accel': {'a': 4.05, 'b': 1.5}, 'drift': {'a': 0.0557, 'b': 0.5}}]
    for demand in demand_params:
        accels = {}
        drifts = {}
        
        demand_type = ""
        for direction in ['X', 'Y']:
            level = Level.objects.get(level=demand['level'], project=project)
            if demand.get('accel'):
                demand_type = 'A'
                params = demand.get('accel')
                curve = EDP_PowerCurve(median_x_a = params['a'],
                                       median_x_b = params['b'],
                                       sd_ln_x_a = 1.5,
                                       sd_ln_x_b = 0.0)
                curve.save()
                accels[direction] = EDP(
                    flavour = EDP_Flavours.objects.get(name_text="Power Curve"),
                    powercurve = curve)
                accels[direction].save()

            if demand.get('drift'):
                demand_type = 'D'
                params = demand.get('drift')
                curve = EDP_PowerCurve(median_x_a = params['a'],
                                       median_x_b = params['b'],
                                       sd_ln_x_a = 1.5,
                                       sd_ln_x_b = 0.0)
                curve.save()
                drifts[direction] = EDP(
                    flavour = EDP_Flavours.objects.get(name_text="Power Curve"),
                    powercurve = curve)
                drifts[direction].save()
        if demand.get('accel'):
            EDP_Grouping(project=project,
                         level=level,
                         type='A',
                         demand_x = accels['X'],
                         demand_y = accels['Y']).save()
        if demand.get('drift'):
            EDP_Grouping(project=project,
                         level=level,
                         type='D',
                         demand_x = drifts['X'],
                         demand_y = drifts['Y']).save()

    # Add components:
    all_floors = range(num_floors + 1)
    not_roof = range(0, num_floors)
    roof = range(num_floors, num_floors+1)
    components = [{'levels': all_floors, 'id': '206', 'quantity': [6, 3, 0]},
                  {'levels': not_roof, 'id': 'B1041.032a', 'quantity': [24, 8, 1]},
                  {'levels': not_roof, 'id': 'B1044.023', 'quantity': [8, 0, 2]},
                  {'levels': not_roof, 'id': 'C1011.001a', 'quantity': [0, 0, 32]},
                  {'levels': roof, 'id': '205', 'quantity': [0, 0, 10]},
                  {'levels': [1, 3, 5], 'id': '206', 'quantity': [1, 2, 5]}]
    for comp in components:
        component = ComponentsTab.objects.get(ident=comp['id'])
        if len(comp['levels']) == 1:
            level = Level.objects.get(project=project, level=comp['levels'][0])
            
            if re.compile(".*Accel").match(component.demand.name):
                demand_type='A'
            elif re.compile(".*Drift").match(component.demand.name):
                demand_type='D'
            else:
                raise ValueError("UNRECOGNIZED DEMAND TYPE FOR COMPONENT: {}".format(component.demand.name))

            demand = EDP_Grouping.objects.get(project=project,
                                              level=level,
                                              type=demand_type)
            group = Component_Group(demand=demand, component=component, 
                                    quantity_x=comp['quantity'][0],
                                    quantity_y=comp['quantity'][1],
                                    quantity_u=comp['quantity'][2])
            group.save()
        else:
            pattern = Component_Group_Pattern(
                project=project,
                component=component,
                quantity_x=comp['quantity'][0],
                quantity_y=comp['quantity'][1],
                quantity_u=comp['quantity'][2],
                cost_adj=1.0,
                comment='Created as a pattern group.')
            pattern.save()

            for l in comp['levels']:
                level = Level.objects.get(project=project, level=l)
                pattern.CreateFromPattern(level)

    return project

@transaction.atomic
def make_example_2(user, title="Example #2", description="This is based on the second example in Brendon Bradley's paper. "):
    project = Project()
    setattr(project, 'title_text', title)
    setattr(project, 'description_text', description)
    setattr(project, 'rarity', 1/500)
    setattr(project, 'mean_im_collapse', 1.2)
    setattr(project, 'sd_ln_im_collapse', 0.47)
    setattr(project, 'mean_cost_collapse', 14E6)
    setattr(project, 'sd_ln_cost_collapse', 0.35)
    
    setattr(project, 'mean_im_demolition', 0.9)
    setattr(project, 'sd_ln_im_demolition', 0.47)
    setattr(project, 'mean_cost_demolition', 14E6)
    setattr(project, 'sd_ln_cost_demolition', 0.35)
    project.save()

    project.AssignRole(user, ProjectUserPermissions.ROLE_FULL)

    # Create levels:
    num_floors = 10
    for l in range(num_floors + 1):
        if l == 0:
            label = "Ground Floor"
        elif l == num_floors:
            label = "Roof"
        else:
            label = "Floor #{}".format(l + 1)
        level = Level(project=project, level=l, label=label)
        level.save()
        
    # Create an IM:
    data = np.genfromtxt('example2/imfunc.csv', comments="#", delimiter=",", invalid_raise=True)
    for d in data:
        if type(d) == list or type(d) == np.ndarray:
            for e in d:
                if isnan(e):
                    raise ValueError("Error importing data")
                else:
                    if isnan(e):
                        raise ValueError("Error importing data")

    hazard = IM()
    hazard.flavour = IM_Types.objects.get(pk=IM_TYPE_INTERP)
    hazard.interp_method = Interpolation_Method.objects.get(method_text="Log-Log")
    hazard.save()
    project.IM = hazard
    #project.save()

    # Insert new points:
    for x, y in data:
        IM_Point(hazard=hazard, im_value=x, rate=y).save()
    project.IM = hazard
    project.save()

    # Create EDPs:
    demand_params = [{'level': 10, 'accel': "RB_EDP21.csv"},
                     {'level': 9, 'accel': "RB_EDP19.csv",  'drift': "RB_EDP20.csv"},
                     {'level': 8, 'accel': "RB_EDP17.csv" ,'drift': "RB_EDP18.csv"},
                     {'level': 7, 'accel': "RB_EDP15.csv" , 'drift': "RB_EDP16.csv" },
                     {'level': 6, 'accel': "RB_EDP13.csv" , 'drift': "RB_EDP14.csv" },
                     {'level': 5, 'accel': "RB_EDP11.csv" , 'drift': "RB_EDP12.csv" },
                     {'level': 4, 'accel': "RB_EDP9.csv" ,  'drift': "RB_EDP10.csv" },
                     {'level': 3, 'accel': "RB_EDP7.csv" , 'drift': "RB_EDP8.csv" },
                     {'level': 2, 'accel': "RB_EDP5.csv" , 'drift': "RB_EDP6.csv" },
                     {'level': 1, 'accel': "RB_EDP3.csv" , 'drift': "RB_EDP4.csv" },
                     {'level': 0, 'accel': "RB_EDP1.csv", 'drift': "RB_EDP2.csv" }]
    for demand in demand_params:
        level = Level.objects.get(project=project, level=demand['level'])
        
        for demand_type in ['accel', 'drift']:
            if demand.get(demand_type):
                if demand_type == 'accel':
                    EDP_demand_type = 'A'
                elif demand_type == 'drift':
                    EDP_demand_type = 'D'
                else:

                    raise ValueError("INVALID DEMAND TYPE")
                
                file = demand.get(demand_type)
                
                data = np.genfromtxt('example2/{}'.format(file), comments="#", delimiter=",", invalid_raise=True)
                # Validate the data:
                for d in data:
                    if type(d) == list or type(d) == np.ndarray:
                        for e in d:
                            if isnan(e):
                                raise ValueError("Error importing data")
                            else:
                                if isnan(e):
                                    raise ValueError("Error importing data")
            
                # Create an array from the points:
                points = [{'im': 0.0, 'mu': 0.0, 'sigma': 0.0}]
                for d in data:
                    if len(d) < 2:
                        raise ValueError("Wrong number of columns")
                    im = d[0]
                    values = d[1:]
                    ln_values = []
                    nz_values = []
                    for value in values:
                        if value != 0:
                            ln_values.append(log(value))
                            nz_values.append(value)
                    median_edp = exp(np.mean(ln_values))
                    sd_ln_edp = np.std(ln_values, ddof=1)
                    points.append({'im': im, 'mu': median_edp, 'sigma': sd_ln_edp})

                edps = {}
                for direction in ['X', 'Y']:
                    edp = EDP(
                        flavour = EDP_Flavours.objects.get(pk=EDP_FLAVOUR_USERDEF),
                        interpolation_method = Interpolation_Method.objects.get(
                            method_text="Linear"))
                    edp.save()
                    edps[direction] = edp

                    for p in points:
                        EDP_Point(demand=edp,
                                  im=p['im'],
                                  median_x=p['mu'],
                                  sd_ln_x=p['sigma']).save()

                EDP_Grouping(project=project, 
                             level=level, 
                             type=EDP_demand_type,
                             demand_x = edps['X'],
                             demand_y = edps['Y']).save()
    # Add components:
    all_floors = range(num_floors + 1)
    not_roof = range(num_floors)
    components = [{'levels': not_roof, 'id': '208', 'quantity': [0, 0, 53]}, # Desktop Computers
                  {'levels': [0], 'id': '204', 'quantity': [0, 0, 2]},
                  {'levels': not_roof, 'id': '214', 'quantity': [0, 0, 10]},
                  {'levels': not_roof, 'id': '203', 'quantity': [0, 0, 693]},
                  {'levels': not_roof, 'id': '211', 'quantity': [23, 23, 0]},
                  {'levels': [1], 'id': '2', 'quantity': [20, 0, 0]},
                  {'levels': range(1, num_floors), 'id': '2', 'quantity': [4, 4, 0]},
                  {'levels': not_roof, 'id': '2', 'quantity': [18, 18, 0]},
                  {'levels': not_roof, 'id': '3', 'quantity': [16, 16, 0]},
                  {'levels': not_roof, 'id': '105', 'quantity': [721, 721, 0]},
                  {'levels': not_roof, 'id': '107', 'quantity': [99, 99, 0]},
                  {'levels': not_roof, 'id': '106', 'quantity': [99, 99, 0]},
                  {'levels': not_roof, 'id': '108', 'quantity': [10, 10, 0]},
                  {'levels': [num_floors], 'id': '205', 'quantity': [4, 4, 0]}]

    for comp in components:
        component = ComponentsTab.objects.get(ident=comp['id'])
        if len(comp['levels']) == 1:
            level = Level.objects.get(project=project, level=comp['levels'][0])
            
            if re.compile(".*Accel").match(component.demand.name):
                demand_type='A'
            elif re.compile(".*Drift").match(component.demand.name):
                demand_type='D'
            else:
                raise ValueError("UNRECOGNIZED DEMAND TYPE FOR COMPONENT: {}".format(component.demand.name))

            demand = EDP_Grouping.objects.get(project=project,
                                              level=level,
                                              type=demand_type)
            group = Component_Group(demand=demand, component=component, 
                                    quantity_x=comp['quantity'][0],
                                    quantity_y=comp['quantity'][1],
                                    quantity_u=comp['quantity'][2])
            group.save()
        else:
            pattern = Component_Group_Pattern(
                project=project,
                component=component,
                quantity_x=comp['quantity'][0],
                quantity_y=comp['quantity'][1],
                quantity_u=comp['quantity'][2],
                cost_adj=1.0,
                comment='Created as a pattern group.')
            pattern.save()

            for l in comp['levels']:
                level = Level.objects.get(project=project, level=l)
                pattern.CreateFromPattern(level)

    return project

class ProjectCreateTypeForm(Form):
    project_type = ChoiceField(choices=[(None, "-------------"),
                                        ("DEMO", "Demo Project"),
                                        ("EMPTY", "Empty Project"),
                                        ("ETABS", "ETABS Project")])

class ETABS_Confirm_Form(Form):
    def __init__(self, request=None, preprocess_id=None):
        super(Form, self).__init__(request)
        if preprocess_id:
            preprocess_data = ETABS_Preprocess.objects.get(id=preprocess_id)
            self.preprocess_data = preprocess_data
            
            period_choices = pickle.loads(preprocess_data.period_choices)
            choices_x = map(lambda x: [x['period'], "{:5.3f}".format(x['ux']) if not np.isnan(x['ux']) else "Manual X Period"],
                            period_choices)
            choices_y = map(lambda x: [x['period'], "{:5.3f}".format(x['uy']) if not np.isnan(x['uy']) else "Manual Y Period"],
                            period_choices)
            self.fields['Tx']=ChoiceField(choices=choices_x, widget=RadioSelect)
            self.fields['Ty']=ChoiceField(choices=choices_y, widget=RadioSelect)

            self.fields['Tx'].widget.attrs['onchange'] = 'Refresh_Tx()'
            self.fields['Ty'].widget.attrs['onchange'] = 'Refresh_Ty()'

            self.fields['Manual_Tx']= FloatField(required=False)
            self.fields['Manual_Tx'].widget.attrs['disabled'] = 'true'
            self.fields['Manual_Tx'].widget.attrs['title'] = "Choose 'Manual X Period' to specify your own X period here."
            self.fields['Manual_Ty']= FloatField(required=False)
            self.fields['Manual_Ty'].widget.attrs['disabled'] = 'true'
            self.fields['Manual_Ty'].widget.attrs['title'] = "Choose 'Manual Y Period' to specify your own Y period here."

            self.fields['Period'] = ChoiceField(choices=[['TX', 'Tx'], ['TY', 'Ty'], ['AVERAGE', 'Average'], ['MANUAL', 'Manual']])
            self.fields['Period'].widget.attrs['onchange'] = 'Refresh_Period()'
            self.fields['Period'].widget.attrs['title'] = 'Select the period to use for the hazard curve.'
            self.fields['Manual_Period'] = FloatField(required=False)
            self.fields['Manual_Period'].widget.attrs['disabled'] = 'true'
            self.fields['Manual_Period'].widget.attrs['title'] = "Choose 'Manual' to specify your own hazard curve period here."
            
            drift_choices = list(map(lambda x: [x, x], pickle.loads(preprocess_data.drift_choices)))
            self.fields['x_drift_case'] = ChoiceField(choices=drift_choices)
            self.fields['y_drift_case'] = ChoiceField(choices=drift_choices)
                                 
            accel_choices = list(map(lambda x: [x, x], pickle.loads(preprocess_data.accel_choices)))
            self.fields['x_accel_case'] = ChoiceField(choices=accel_choices)
            self.fields['y_accel_case'] = ChoiceField(choices=accel_choices)

            self.fields['yield_strength'] = FloatField(required=True)
            self.fields['yield_strength'].label = 'Yield Strength'
            self.fields['yield_strength'].widget.attrs['title'] = "Enter the yield strength, if you know it, or use the default."
            self.fields['yield_strength'].widget.attrs['style'] = "text-align:right"
            
@login_required
def clean_project(request, project_id):
    if request.method == 'GET':
        # Fetch an existing project
        project = get_object_or_404(Project, pk=project_id)
        if not project.CanRead(request.user):
            raise PermissionDenied

        Clean_Project.delay(project_id).get()
        return HttpResponseRedirect(reverse('slat:project', args=(project.id,))) 
        
    else:
        # Shouldn't get here
        raise PermissionDenied
    
@login_required
def project(request, project_id=None):
    # Initialize everything we'll send to the template:
    form = None
    levels = None
    users = None
    groups = None
    can_add = None
    project_type_form = None
    form1 = None
    form2 = None
    form3 = None
    chart = None
    pdf_chart = None

    # Four cases to consider:
    #     - GET with no project id: create a blank form for a new project
    #     - GET with a project id: create a form for the existing project
    #     - POST with no project id: create new project, from the form data
    #     - POST with project id: update existing project, from the form data
    #
    if request.method == 'GET' and not project_id:
        # Create a blank form for a new project
        form = ProjectForm()
        form1 = ProjectFormPart1()
        form2 = ProjectFormPart2()
        form3 = ProjectFormPart3()
        levels = None
        levels_form = LevelsForm()
        users = None
        groups = None
        can_add = False
        project_type_form = ProjectCreateTypeForm()
        project_type_form.fields['project_type'].widget.attrs['onchange'] = 'Refresh()'
        
        return render(request, 'slat/project.html', { 
                'form': form,
                'form1': form1, 
                'form2': form2, 
                'form3': form3, 
                'levels': levels, 
                'chart': chart,
                'pdfchart': pdf_chart,
                'users': users, 
                'groups': groups,
                'can_add': can_add,
                'project_type_form': project_type_form})
    elif request.method == 'GET' and project_id:
        # Fetch an existing project
        project = get_object_or_404(Project, pk=project_id)
        if not project.CanRead(request.user):
            raise PermissionDenied
                
        can_add = project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL
        form = ProjectForm(instance=project, initial=model_to_dict(project))

        levels = project.num_levels()
        levels_form = None
        users = list(ProjectUserPermissions.objects.filter(project=project, role=ProjectUserPermissions.ROLE_FULL))
        groups = []
        for g in ProjectGroupPermissions.objects.filter(project=project):
            groups.append(g.group)

        job = Project_Basic_Stats.delay(project_id)

        return render(request, 'slat/project.html', { 
            'task_id': job.id,
            'form': form,
            'form3': form3, 
            'levels': levels, 
            'chart': chart,
            'pdfchart': pdf_chart,
            'users': users, 
            'groups': groups,
            'can_add': can_add,
            'project': project,
            'project_type_form': project_type_form})
    
    elif request.method == 'POST' and not project_id:
        # Create a new project from the form
        project = None
        form1 = ProjectFormPart1(request.POST)
        form1.is_valid()
        title = form1.cleaned_data["title"]
        description = form1.cleaned_data["description"]
        project_type_form = ProjectCreateTypeForm(request.POST)
        if project_type_form.is_valid():
            project_type = project_type_form.cleaned_data["project_type"]
            
            if project_type == "DEMO":
                project = make_example_2(request.user, title, description)
            elif project_type == "EMPTY":
                form2 = ProjectFormPart2(request.POST)
                if (form2.is_valid()):
                    rarity = form2.cleaned_data["rarity"]
                    levels = form2.cleaned_data["levels"]
                    project = Project()
                    setattr(project, 'title_text', title)
                    setattr(project, 'description_text', description)
                    setattr(project, 'rarity', 1/500)
                    project.save()
                    for l in range(levels + 1):
                        if l == 0:
                            label = "Ground Floor"
                        elif l == levels:
                            label = "Roof"
                        else:
                            label = "Floor #{}".format(l + 1)
                        level = Level(project=project, level=l, label=label)
                        level.save()

                        # Create empty demands:
                        edp_x = EDP()
                        edp_x.save()
                        edp_y = EDP()
                        edp_y.save()
                        edp = EDP_Grouping(project=project,
                                           level=level,
                                           demand_x=edp_x,
                                           demand_y=edp_y,
                                           type = EDP_Grouping.EDP_TYPE_ACCEL)
                        edp.save()

                        if l != levels:
                            edp_x = EDP()
                            edp_x.save()
                            edp_y = EDP()
                            edp_y.save()
                            edp = EDP_Grouping(project=project,
                                               level=level,
                                               demand_x=edp_x,
                                               demand_y=edp_y,
                                               type = EDP_Grouping.EDP_TYPE_DRIFT)
                            edp.save()
                else:
                    eprint("Error in Form2")
                project.AssignRole(request.user, ProjectUserPermissions.ROLE_FULL)
                return HttpResponseRedirect(reverse('slat:hazard_choose', args=(project.id,))) 
            elif project_type == "ETABS":
                form3 = ProjectFormPart3(request.POST, request.FILES)
                if (form3.is_valid()):
                
                    file_path = form3.cleaned_data['path'].name
                    file_data = request.FILES['path'].file.read()
                    constant_R = form3.cleaned_data["constant_R"]
                    constant_I = form3.cleaned_data["constant_I"]
                    constant_Omega = form3.cleaned_data["constant_Omega"]
                    contents = file_data
                    location = form3.cleaned_data["location"]
                    soil_class = form3.cleaned_data["soil_class"]
                    return_period = int(form3.cleaned_data["return_period"])
                    frame_type_x = form3.cleaned_data["frame_type_x"]
                    frame_type_y = form3.cleaned_data["frame_type_y"]

                    preprocess_id = ETABS_preprocess(
                        title, description, 
                        constant_R, constant_I, constant_Omega,
                        file_data, file_path,
                        location, soil_class, return_period,
                        frame_type_x, frame_type_y,
                        request.user.id)
                    
                    return HttpResponseRedirect(reverse('slat:etabs_confirm', args=(preprocess_id,)))
                else:
                    print("INVALID")
                    print(form3.errors)
                    
                    return render(request, 'slat/project.html', { 
                        'form': form,
                        'form1': form1, 
                        'form2': form2, 
                        'form3': form3, 
                        'levels': levels, 
                        'chart': chart,
                        'pdfchart': pdf_chart,
                        'users': users, 
                        'groups': groups,
                        'can_add': can_add,
                        'project_type_form': project_type_form})

        project.AssignRole(request.user, ProjectUserPermissions.ROLE_FULL)
        return HttpResponseRedirect(reverse('slat:project', args=(project.id,)))
    elif request.method == 'POST' and project_id:
        # Update existing project from form
        project = Project.objects.get(pk=project_id)
        form = ProjectForm(request.POST, Project.objects.get(pk=project_id), initial=model_to_dict(project))
        form.instance.id = project_id

        if not form.is_valid():
            print("INVALID")
            print(form.errors)
            return render(request, 'slat/project.html', { 
                'form': form,
                'form1': form1, 
                'form2': form2, 
                'form3': form3, 
                'levels': levels, 
                'chart': chart,
                'pdfchart': pdf_chart,
                'users': users, 
                'groups': groups,
                'can_add': can_add,
                'project_type_form': project_type_form})
    
        else:
            form.save()
            return HttpResponseRedirect(reverse('slat:project', args=(form.instance.id,)))
    else:
        # This should never happen!
        raise(ValueError("Unknown method or project_id"))

@login_required
def copy_components(request, dest_project_id):
    dest_project = get_object_or_404(Project, pk=dest_project_id)
    if request.POST:
        if request.POST.get('clean'):
            with transaction.atomic():
                # Remove all component groups and patterns associated with this project:
                Component_Group.objects.filter(demand__project=dest_project).delete()
                Component_Group_Pattern.objects.filter(project=dest_project).delete()

        # Import component groups
        src_project_id = request.POST['source']
        src_project = get_object_or_404(Project, pk=src_project_id)

        # Find components/patterns that we need to copy:
        with transaction.atomic():
            pattern_map = {}
            for pattern in Component_Group_Pattern.objects.filter(project=src_project):
                new_pattern = Component_Group_Pattern(
                    project = dest_project,
                    component = pattern.component,
                    quantity_x = pattern.quantity_x,
                    quantity_y = pattern.quantity_y,
                    quantity_u = pattern.quantity_u,
                    cost_adj = pattern.cost_adj,
                    comment = pattern.comment)
                new_pattern.save()
                pattern_map[pattern.id] = new_pattern.id

            for cg in Component_Group.objects.filter(demand__project=src_project).order_by("component"):
                if cg.demand.level.level > dest_project.num_levels():
                    continue

                pattern = cg.pattern and Component_Group_Pattern.objects.get(id = pattern_map[cg.pattern.id])
                level = Level.objects.get(project=dest_project, level=cg.demand.level.level)
                demand_type = cg.demand.type
                demand = EDP_Grouping.objects.get(
                    project=dest_project,
                    level=level,
                    type=demand_type)

                new_group = Component_Group(
                    component= cg.component,
                    cost_adj = cg.cost_adj,
                    quantity_x=cg.quantity_x,
                    quantity_y= cg.quantity_y,
                    quantity_u= cg.quantity_u,
                    comment= cg.comment,
                    pattern = pattern,
                    demand=demand)
                new_group.save()

        return HttpResponseRedirect(reverse('slat:project', args=(dest_project_id,)))
    else:
        # Present choices
        project_list = []
        for project in Project.objects.all():
            if project.CanRead(request.user) and not project == dest_project:
                project_list.append(project)
                context = {'dest_project': dest_project,
                           'project_list': project_list}
                
        return render(request, 'slat/copy_components.html', context)
    
@login_required
def hazard(request, project_id):
    # If the project doesn't exist, generate a 404:
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    # Otherwise:
    #    - Does the project already have a hazard defined? If so, we'll
    #      redirect to the 'view' page for that type of hazard
    #    - If not, we'll redirect to the 'choose' page:
    hazard = project.IM

    if not hazard:
            form = HazardForm()
            return HttpResponseRedirect(reverse('slat:hazard_choose', args=(project_id,)))
    else:        
        # Hazard exists:
        flavour = hazard.flavour
        if flavour.id == IM_TYPE_NLH:
            form = NLHForm(instance=hazard.nlh)
            return HttpResponseRedirect(reverse('slat:nlh', args=(project_id,)))
        elif flavour.id == IM_TYPE_INTERP:
            return HttpResponseRedirect(reverse('slat:im_interp', args=(project_id,)))
        elif flavour.id == IM_TYPE_NZS:
            return HttpResponseRedirect(reverse('slat:nzs', args=(project_id,)))
        else:
            raise ValueError("UNKNOWN HAZARD TYPE")
        
@login_required
def hazard_choose(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    
    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied
    
    hazard = project.IM

    if request.POST:
        if request.POST.get('cancel'):
            # If the form was CANCELled, return the user to the project page (if no hazard has been defined),
            # or to the page for the current hazard (they got here because they cancelled a change to the 
            # hazard type):
            if hazard:
                # Shouldn't get here, but if we do, just redirect to the "choose hazard" page:
                return HttpResponseRedirect(reverse('slat:hazard', args=(project_id)))
            else:
                return HttpResponseRedirect(reverse('slat:project', args=(project_id)))
        elif not hazard:
            # The form was submitted, but the project doesn't have a hazard yet. Go straight
            # to the approporite 'edit' page to let the user enter data:
            if request.POST.get('flavour'):
                flavour = IM_Types.objects.get(pk=request.POST.get('flavour'))
                if flavour.id == IM_TYPE_NLH:
                    return HttpResponseRedirect(reverse('slat:nlh_edit', args=(project_id,)))
                elif flavour.id == IM_TYPE_INTERP:
                    return HttpResponseRedirect(reverse('slat:im_interp_edit', args=(project_id,)))
                elif flavour.id == IM_TYPE_NZS:
                    return HttpResponseRedirect(reverse('slat:im_nzs_edit', args=(project_id,)))
                else:
                    raise ValueError("UNKNOWN HAZARD TYPE")
            else:
                # Shouldn't get here, but if we do, just redirect to the "choose hazard" page:
                return HttpResponseRedirect(reverse('slat:hazard_choose', args=(project_id,)))
        else:        
            # Hazard exists. If the chosen type already, exists, save the change and go to the
            # 'view' page for the hazard. Otherwise, don't save the change, but go to the 'edit'
            # page.
            flavour = IM_Types.objects.get(pk=request.POST.get('flavour'))
            if flavour.id == IM_TYPE_NLH:
                if hazard.nlh:
                    hazard.flavour = flavour
                    hazard.save()
                    hazard._make_model()
                    return HttpResponseRedirect(reverse('slat:nlh', args=(project_id,)))
                else:
                    return HttpResponseRedirect(reverse('slat:nlh_edit', args=(project_id,)))
            elif flavour.id == IM_TYPE_INTERP:
                if hazard.interp_method:
                    hazard.flavour = flavour
                    hazard.save()
                    hazard._make_model()
                    return HttpResponseRedirect(reverse('slat:im_interp', args=(project_id,)))
                else:
                    return HttpResponseRedirect(reverse('slat:im_interp_edit', args=(project_id,)))
            if flavour.id == IM_TYPE_NZS:
                if hazard.nzs:
                    hazard.flavour = flavour
                    hazard.save()
                    hazard._make_model()
                    return HttpResponseRedirect(reverse('slat:nzs', args=(project_id,)))
                else:
                    return HttpResponseRedirect(reverse('slat:im_nzs_edit', args=(project_id,)))
            else:
                raise ValueError("UNKNOWN HAZARD TYPE")
    else:
        if hazard:
            form = HazardForm(instance=hazard)
        else:
            form = HazardForm(initial={'flavour': IM_TYPE_NZS})

        return render(request, 'slat/hazard_choose.html', {'form': form, 
                                                           'project_id': project_id,
                                                           'title': project.title_text })

class HazardPlot(Chart):
    chart_type = 'line'
    legend = Legend(display=False)
    title = Title(display=True, text="Hazard Curve")
    scales = {
        'xAxes': [Axes(type='logarithmic', 
                       position='bottom', 
                       scaleLabel=ScaleLabel(display=True, 
                                             labelString='Intensity Measure'))],
        'yAxes': [Axes(type='logarithmic', 
                       position='left',
                       scaleLabel=ScaleLabel(display=True, 
                                             labelString='Annual Rate of Exceedance'))]
    }
    
    
    def __init__(self, hazard):
        super(HazardPlot, self).__init__()
        self.title['text'] = 'Hazard Curve for {}'.format(Project.objects.get(IM=hazard).title_text)
        self.scales['xAxes'][0]['scaleLabel']['labelString'] = hazard.label()
        
        if hazard.model():
            im_func = hazard.model()
            xlimit = im_func.plot_max()

            self.data =  []
            
            N = 25
            for i in range(1,N +1):
                x = i/N * xlimit
                y = im_func.getlambda(x)
                self.data.append({'x': x, 'y': y})

    def get_datasets(self, *args, **kwargs):
        return [
            DataSet(
                type='line',
                data=self.data,
                borderColor=rgba(0x34,0x64,0xC7,1.0),
                backgroundColor=rgba(0,0,0,0)
            )]

    
@login_required
def nlh(request, project_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied
    
    hazard = project.IM

    if request.method == 'POST':
        return HttpResponseRedirect(reverse('slat:hazard_choose', args=(project_id)))
    else:
        if hazard and hazard.nlh:
            return render(request, 'slat/nlh.html', {'nlh':hazard.nlh, 'title': project.title_text, 
                                                     'project_id': project_id, 
                                                     'chart': HazardPlot(hazard)})
        else:
            return HttpResponseRedirect(reverse('slat:hazard_choose', args=(project_id)))
            

@login_required
def nlh_edit(request, project_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    hazard = project.IM

    if request.method == 'POST':
        if request.POST.get('cancel'):
            if hazard:
                return HttpResponseRedirect(reverse('slat:hazard', args=(project_id)))
            else:
                return HttpResponseRedirect(reverse('slat:project', args=(project_id)))

        project = get_object_or_404(Project, pk=project_id)
        hazard = project.IM

        if not hazard or not hazard.nlh:
            form = NLHForm(request.POST)
        else:
            form = NLHForm(request.POST, instance=hazard.nlh)
        form.save()
        if not hazard:
            hazard = IM()
        hazard.nlh = form.instance
        hazard.flavour = IM_Types.objects.get(pk=IM_TYPE_NLH)
        hazard.save()
        hazard._make_model()
        project.IM = hazard
        project.save()

        return HttpResponseRedirect(reverse('slat:nlh', args=(project_id,)))
    else:
        if hazard and hazard.nlh:
            form = NLHForm(instance=hazard.nlh)
        else:
            form = NLHForm()

    return render(request, 'slat/nlh_edit.html', {'form': form, 'project_id': project_id,
                                                  'title': project.title_text})

@login_required
def im_interp(request, project_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    hazard = project.IM

    if request.method == 'POST':
        project = get_object_or_404(Project, pk=project_id)
        hazard = project.IM

        if not hazard or not hazard.interp_method:
            form = Interpolation_Method_Form(request.POST)
        else:
            form = Interpolation_Method_Form(request.POST, initial={'method': hazard.interp_method.id})
        form.save()

        if not hazard:
            hazard = IM()
        if form.is_valid():
            hazard.interp_method = Interpolation_Method.objects.get(pk=form.cleaned_data['method'])

        hazard.flavour = IM_Types.objects.get(pk=IM_TYPE_INTERP)
        hazard.save()
        hazard._make_model()
        project.IM = hazard
        project.save()
        
        Point_Form_Set = modelformset_factory(IM_Point, can_delete=True, fields=('im_value', 'rate'), extra=3)
        formset = Point_Form_Set(request.POST, queryset=IM_Point.objects.filter(hazard=hazard).order_by('im_value'))

        instances = formset.save(commit=False)

        for instance in instances:
            instance.hazard = hazard
            if instance.im_value==0 and instance.rate==0:
                instance.delete()
            else:
                instance.save()

        # Rebuild the form from the database; this removes any deleted entries
        formset = Point_Form_Set(queryset=IM_Point.objects.filter(hazard=hazard).order_by('im_value'))
        return render(request, 'slat/im_interp.html', {'form': form, 'points': formset,
                                                       'project_id': project_id, 'title': project.title_text})
            
    # if a GET (or any other method) we'll create a blank form
    elif hazard:
        points = IM_Point.objects.filter(hazard=hazard).order_by('im_value')
        method = hazard.interp_method

        chart = HazardPlot(hazard)

        return render(request, 'slat/im_interp.html', {'method': method, 'points': points,
                                                       'project_id': project_id,
                                                       'chart': chart,
                                                       'title': project.title_text})
    else:
        # Shouldn't get here, but if we do, just redirect to the "choose hazard" page:
        return HttpResponseRedirect(reverse('slat:hazard_choose', args=(project_id,)))
        
    return render(request, 'slat/im_interp.html', {'method': method, 'points': points, 
                                                   'project_id': project_id,
                                                   'title': project.title_text})

@login_required
def im_interp_edit(request, project_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    hazard = project.IM

    if request.method == 'POST':
        project = get_object_or_404(Project, pk=project_id)
        hazard = project.IM

        if request.POST.get('cancel'):
            if hazard:
                return HttpResponseRedirect(reverse('slat:hazard', args=(project_id)))
            else:
                return HttpResponseRedirect(reverse('slat:project', args=(project_id)))

        if not hazard or not hazard.interp_method:
            form = Interpolation_Method_Form(request.POST)
        else:
            form = Interpolation_Method_Form(request.POST, initial={'method': hazard.interp_method.id})

        if not hazard:
            hazard = IM()
        if form.is_valid():
            hazard.interp_method = Interpolation_Method.objects.get(pk=form.cleaned_data['method'])
        hazard.flavour = IM_Types.objects.get(pk=IM_TYPE_INTERP)
        hazard.save()
        hazard._make_model()
        project.IM = hazard
        project.save()

        Point_Form_Set = modelformset_factory(IM_Point, can_delete=True, exclude=('id', 'hazard',), extra=3)
        formset = Point_Form_Set(request.POST, queryset=IM_Point.objects.filter(hazard=hazard).order_by('im_value'))

        if not formset.is_valid():
            print(formset.errors)
        instances = formset.save(commit=False)

        for f in formset.deleted_forms:
            f.instance.delete()
            
        for instance in instances:
            if instance.id and instance.DELETE:
                instance.delete()
            else:
                instance.hazard = hazard
                instance.save()

        if request.POST.get('done'):
            return HttpResponseRedirect(reverse('slat:im_interp', args=(project_id)))
        else:
            # Rebuild the form from the database; this removes any deleted entries
            formset = Point_Form_Set(queryset=IM_Point.objects.filter(hazard=hazard).order_by('im_value'))
            return render(request, 'slat/im_interp_edit.html', {'form': form, 'points': formset, 
                                                                'project_id': project_id,
                                                                'title': project.title_text})
            
    # if a GET (or any other method) we'll create a blank form
    else:
        Point_Form_Set = modelformset_factory(IM_Point, can_delete=True, exclude=('hazard',), widgets={'id': HiddenInput}, extra=3)
        if hazard and hazard.interp_method:
            form = Interpolation_Method_Form(initial={'method': hazard.interp_method.id})
            formset = Point_Form_Set(queryset=IM_Point.objects.filter(hazard=hazard).order_by('im_value'))
        else:
            form = Interpolation_Method_Form(initial={'method': INTERP_LOGLOG})
            formset = Point_Form_Set(queryset=IM_Point.objects.none())

    return render(request, 'slat/im_interp_edit.html', {'form': form, 'points': formset,
                                                        'project_id': project_id,
                                                        'title': project.title_text})

@login_required
def im_file(request, project_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    hazard = project.IM

    if request.method == 'POST':
        interp_form = Interpolation_Method_Form(request.POST)
        form = Input_File_Form(request.POST, request.FILES)

        try:
            # Now save the data. First make sure the database hierarchy is present:
            if not hazard:
                hazard = IM()
            if interp_form.is_valid():
                hazard.interp_method = Interpolation_Method.objects.get(pk=interp_form.cleaned_data['method'])
            else:
                hazard.interp_method = Interpolation(method=Interpolation_Method.objects.get(pk=INTERP_LOGLOG))
                
            if form.is_valid():
                if form.cleaned_data['flavour'].id == INPUT_FORMAT_CSV:
                    data = np.genfromtxt(request.FILES['path'].file, comments="#", delimiter=",", invalid_raise=True)
                    for d in data:
                        if type(d) == list or type(d) == np.ndarray:
                            for e in d:
                                if isnan(e):
                                    raise ValueError("Error importing data")
                        else:
                            if isnan(d):
                                raise ValueError("Error importing data")
                elif form.cleaned_data['flavour'].id == INPUT_FORMAT_LEGACY:
                    data = np.loadtxt(request.FILES['path'].file, skiprows=2)
                else:
                    raise ValueError("Unrecognised file format specified.")
                    
            if len(data[0]) != 2:
                raise ValueError("Wrong number of columns")


            hazard.flavour = IM_Types.objects.get(pk=IM_TYPE_INTERP)
            hazard.save()
            project.IM = hazard
            project.save()
            # Remove any existing points:
            IM_Point.objects.filter(hazard = hazard).delete()
            
            # Insert new points:
            for x, y in data:
                IM_Point(hazard=hazard, im_value=x, rate=y).save()

            hazard._make_model()
            return HttpResponseRedirect(reverse('slat:im_interp', args=(project_id,)))
        except ValueError as e:
            data = None
            form.add_error(None, 'There was an error importing the file.')

        return render(request, 'slat/im_file.html', {'form': form,
                                                     'interp_form': interp_form,
                                                     'project_id': project_id,
                                                     'title': project.title_text,
                                                     'data': data})
            
    # if a GET (or any other method) we'll create a blank form
    else:
        form = Input_File_Form()
        if hazard and hazard.interp_method:
            interp_form = Interpolation_Method_Form(initial={'method': hazard.interp_method.id})
        else:
            interp_form = Interpolation_Method_Form()
        form.fields['path'].widget.attrs['class'] = 'normal'
        form.fields['path'].widget.attrs['title'] = 'Choose the input file'
        
        return render(request, 'slat/im_file.html', {'form': form, 
                                                     'interp_form': interp_form,
                                                     'project_id': project_id,
                                                     'title': project.title_text})
    

@login_required
def im_nzs(request, project_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    hazard = project.IM

    if request.method == 'POST':
        # Shouldn't get here, but if we do, just redirect to the "choose hazard" page:
        return HttpResponseRedirect(reverse('slat:hazard_choose', args=(project_id,)))
    else:
        if hazard and hazard.nzs:
            chart = HazardPlot(hazard)
        
            return render(request, 'slat/nzs.html', {'nzs':hazard.nzs, 'title': project.title_text, 
                                                     'project_id': project_id, 
                                                     'chart': chart})
        else:
            # Shouldn't get here, but if we do, just redirect to the "choose hazard" page:
            return HttpResponseRedirect(reverse('slat:hazard_choose', args=(project_id,)))
            

@login_required
def im_nzs_edit(request, project_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    hazard = project.IM

    if request.method == 'POST':
        if request.POST.get('cancel'):
            if hazard:
                return HttpResponseRedirect(reverse('slat:hazard', args=(project_id)))
            else:
                return HttpResponseRedirect(reverse('slat:project', args=(project_id)))

        if request.POST.get('edit'):
            return HttpResponseRedirect(reverse('slat:im_nzs_edit', args=(project_id)))
        
        project = get_object_or_404(Project, pk=project_id)
        hazard = project.IM

        if not hazard or not hazard.nzs:
            form = NZSForm(request.POST)
        else:
            form = NZSForm(request.POST, instance=hazard.nzs)
        form.save()

        if not hazard:
            hazard = IM()
        hazard.nzs = form.instance
        hazard.nzs.save()
        hazard.flavour = IM_Types.objects.get(pk=IM_TYPE_NZS)
        hazard.save()
        hazard._make_model()
        project.IM = hazard
        project.save()

        return HttpResponseRedirect(reverse('slat:nzs', args=(project_id,)))
    
    else:
        if hazard and hazard.nzs:
            form = NZSForm(instance=hazard.nzs)
        else:
            form = NZSForm()

    return render(request, 'slat/nzs_edit.html', {'form': form, 'project_id': project_id,
                                                     'title': project.title_text})
    

class IMDemandPlot(Chart):
    chart_type = 'line'
    legend = Legend(display=True)
    title = Title(display=True, text="Hazard Curve")
    scales = {
        'xAxes': [Axes(type='linear', 
                       position='bottom', 
                       scaleLabel=ScaleLabel(display=True, 
                                             labelString='Intensity Measure'))],
        'yAxes': [Axes(type='linear', 
                       position='left',
                       scaleLabel=ScaleLabel(display=True, 
                                             labelString='Demand'))]
    }
    
    
    def __init__(self, demand):
        super(IMDemandPlot, self).__init__()
        try:
            group = demand.demand_x
        except:
            group = demand.demand_y
            
        demand_func = demand.model()
        if demand_func:
            if group.type == 'D':
                demand_type  = 'Drift (radians)'
            elif group.type == 'A':
                demand_type  = 'Acceleration (g)'
            else:
                demand_type = 'Unknown'
            
            self.title['text'] = "{} {}".format(group.level.label, demand_type)
            self.scales['yAxes'][0]['scaleLabel']['labelString'] = demand_type
            xlimit = group.project.IM.model().plot_max()

            self.median =  []
            self.x_10 = []
            self.x_90 = []
            N = 25
            for i in range(1,N +1):
                x = i/N * xlimit
                median = demand_func.Median(x)
                x_10 = demand_func.X_at_exceedence(x, 0.10)
                x_90 = demand_func.X_at_exceedence(x, 0.90)

                self.median.append({'x': x, 'y': median})
                self.x_10.append({'x': x, 'y': x_10})
                self.x_90.append({'x': x, 'y': x_90})
                
    def get_datasets(self, *args, **kwargs):
        return [
            DataSet(
                type='line',
                label='Median',
                data=self.median,
                borderColor=rgba(255,99,132,1.0),
                backgroundColor=rgba(0,0,0,0)
            ),
            DataSet(
                type='line',
                label='10%',
                data=self.x_10,
                borderColor=rgba(54, 262, 235, 1.0),
                backgroundColor=rgba(0,0,0,0)
            ),
            DataSet(
                type='line',
                label='90%',
                data=self.x_90,
                borderColor=rgba(74, 192, 191, 1.0),
                backgroundColor=rgba(0,0,0,0)
            )]

class DemandRatePlot(Chart):
    chart_type = 'line'
    legend = Legend(display=False)
    title = Title(display=True, text="Rate of Exceedence Curve")
    scales = {
        'xAxes': [Axes(type='linear', 
                       position='bottom', 
                       scaleLabel=ScaleLabel(display=True, 
                                             labelString='Demand'))],
        'yAxes': [Axes(type='linear', 
                       position='left',
                       scaleLabel=ScaleLabel(display=True, 
                                             labelString='Annual Rate of Exceedance'))]
    }
    
    
    def __init__(self, demand):
        super(DemandRatePlot, self).__init__()
        try:
            group = demand.demand_x
        except:
            group = demand.demand_y
            
        demand_func = demand.model()
        if demand_func:
            if group.type == 'D':
                demand_type  = 'Drift (radians)'
            elif group.type == 'A':
                demand_type  = 'Acceleration (g)'
            else:
                demand_type = 'Unknown'
            
            self.title['text'] = "{} {} Rate of Exceedance".format(group.level.label, demand_type)
            self.scales['xAxes'][0]['scaleLabel']['labelString'] = demand_type
            
            xlimit = demand_func.plot_max()
            self.rate =  []
            N = 25
            for i in range(1,N +1):
                x = i/N * xlimit
                rate = demand_func.getlambda(x)
                self.rate.append({'x': x, 'y': rate})
                
    def get_datasets(self, *args, **kwargs):
        return [
            DataSet(
                type='line',
                data=self.rate,
                borderColor=rgba(255,99,132,1.0),
                backgroundColor=rgba(0,0,0,0))]

class DemandRatesPlot1(Chart):
    chart_type = 'line'
    legend = Legend(display=True)
    title = Title(display=True)
    scales = {
        'xAxes': [Axes(type='linear', 
                       position='bottom', 
                       scaleLabel=ScaleLabel(display=True, 
                                             labelString='Demand'))],
        'yAxes': [Axes(type='linear', 
                       position='left',
                       scaleLabel=ScaleLabel(display=True, 
                                             labelString='Annual Rate of Exceedance'))]
    }
    
    
    def __init__(self, demand_group):
        super(DemandRatesPlot1, self).__init__()
        if demand_group.demand_x.model():
            if demand_group.type == 'D':
                demand_type  = 'Drift (radians)'
            elif demand_group.type == 'A':
                demand_type  = 'Acceleration (g)'
            else:
                demand_type = 'Unknown'

            self.title['text'] = "".join("{} {} Rate of Exceedance".format(demand_group.level.label,
                                                                   demand_type))
            self.scales['xAxes'][0]['scaleLabel']['labelString'] = demand_type
            
            xlimit = max(demand_group.demand_x.model().plot_max(),
                         demand_group.demand_y.model().plot_max())
            self.rate_x =  []
            self.rate_y = []
            N = 25
            for i in range(1,N +1):
                x = i/N * xlimit
                rate = demand_group.demand_x.model().getlambda(x)
                self.rate_x.append({'x': x, 'y': rate})
                rate = demand_group.demand_y.model().getlambda(x)
                self.rate_y.append({'x': x, 'y': rate})
        else:
             eprint("SKIPPING")   
                
    def get_datasets(self, *args, **kwargs):
        return [
            DataSet(
                type='line',
                label='X',
                data=self.rate_x,
                borderWidth=3,
                borderDash=[5, 5],
                borderColor=rgba(255, 0, 0, 1.0),
                backgroundColor=rgba(0,0,0,0)),
            DataSet(
                type='line',
                label='Y',
                data=self.rate_y,
                borderWidth=3,
                borderColor=rgba(0, 255, 0, 1.0),
                borderDash=[5, 5],
                borderDashOffset=5,
                backgroundColor=rgba(0,0,0,0))]

class DemandRatesPlot2(Chart):
    chart_type = 'line'
    legend = Legend(display=True)
    title = Title(display=True)
    scales = {
        'xAxes': [Axes(type='linear', 
                       position='bottom', 
                       scaleLabel=ScaleLabel(display=True, 
                                             labelString='Demand'))],
        'yAxes': [Axes(type='linear', 
                       position='left',
                       scaleLabel=ScaleLabel(display=True, 
                                             labelString='Annual Rate of Exceedance'))]
    }
    
    
    def __init__(self, demand_group):
        super(DemandRatesPlot2, self).__init__()
        if demand_group.demand_x.model():
            if demand_group.type == 'D':
                demand_type  = 'Drift (radians)'
            elif demand_group.type == 'A':
                demand_type  = 'Acceleration (g)'
            else:
                demand_type = 'Unknown'

            self.title['text'] = "".join("{} {} Rate of Exceedance".format(demand_group.level.label,
                                                                   demand_type))
            self.scales['xAxes'][0]['scaleLabel']['labelString'] = demand_type
            
            xlimit = max(demand_group.demand_x.model().plot_max(),
                         demand_group.demand_y.model().plot_max())
            self.rate_x =  []
            self.rate_y = []
            N = 25
            for i in range(1,N +1):
                x = i/N * xlimit
                rate = demand_group.demand_x.model().getlambda(x)
                self.rate_x.append({'x': x, 'y': rate})
                rate = demand_group.demand_y.model().getlambda(x)
                self.rate_y.append({'x': x, 'y': rate})
                
    def get_datasets(self, *args, **kwargs):
        return [
            DataSet(
                type='line',
                label='X',
                data=self.rate_x,
                borderWidth=3,
                borderColor=rgba(255, 0, 0, 1.0),
                borderDash=[5, 5],
                backgroundColor=rgba(0,0,0,0)),
            DataSet(
                type='line',
                label='Y',
                data=self.rate_y,
                borderWidth=3,
                borderColor=rgba(0, 255, 0,1.0),
                borderDash=[5, 5],
                borderDashOffset=5,
                backgroundColor=rgba(0,0,0,0))]

@login_required
def edp_view(request, project_id, edp_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    edp = get_object_or_404(EDP, pk=edp_id)
        
    if request.method == 'POST':
        raise ValueError("SHOULD NOT GET HERE")
    else:
        flavour = edp.flavour
        if not flavour:
            return HttpResponseRedirect(reverse('slat:edp_choose', args=(project_id, edp_id)))
        elif flavour.id == EDP_FLAVOUR_POWERCURVE:
            return HttpResponseRedirect(reverse('slat:edp_power', args=(project_id, edp_id)))
        elif flavour.id == EDP_FLAVOUR_USERDEF:
            return HttpResponseRedirect(reverse('slat:edp_userdef', args=(project_id, edp_id)))
        else:
            raise ValueError("edp_view not implemented")
    
@login_required
def edp_init(request, project_id):
    # If the project doesn't exist, generate a 404:
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    if request.method == 'POST':
        project.floors = int(request.POST.get('floors'))
        project.save()
        for f in range(int(project.floors) + 1):
            EDP(project=project,
                level=f,
                type=EDP_Grouping.EDP_TYPE_ACCEL).save()
            if f > 0:
                EDP(project=project,
                    level=f,
                    type=EDP.EDP_TYPE_DRIFT).save()
        return HttpResponseRedirect(reverse('slat:edp', args=(project_id)))
    else:
        return render(request, 'slat/edp_init.html', {'project': project, 'form': FloorsForm()})
    
@login_required
def edp_choose(request, project_id, edp_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    edp = get_object_or_404(EDP, pk=edp_id)
    
    if request.POST:
        if request.POST.get('cancel'):
            # If the form was CANCELled, return the user to the EDP page
            return HttpResponseRedirect(reverse('slat:edp', args=(project_id)))
        
        flavour = EDP_Flavours.objects.get(pk=request.POST.get('flavour'))
        if flavour.id == EDP_FLAVOUR_USERDEF:
            return HttpResponseRedirect(reverse('slat:edp_userdef_edit', args=(project_id, edp_id)))
        elif flavour.id == EDP_FLAVOUR_POWERCURVE:
            return HttpResponseRedirect(reverse('slat:edp_power_edit', args=(project_id, edp_id)))
        else:
            raise ValueError("EDP_CHOOSE: Unrecognized choice '{}'".format(flavour))
            
    else:
        form = EDPForm()
        return render(request, 'slat/edp_choose.html', {'form': form, 
                                                        'project': project,
                                                        'edp': edp})
    raise ValueError("EDP_CHOOSE not implemented")

@login_required
def edp_power(request, project_id, edp_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    edp = get_object_or_404(EDP, pk=edp_id)
    charts = [IMDemandPlot(edp), DemandRatePlot(edp)]
    return render(request, 'slat/edp_power.html', {'project': project, 'edp': edp, 'charts': charts})

@login_required
def edp_power_edit(request, project_id, edp_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    edp = get_object_or_404(EDP, pk=edp_id)
    
    if request.POST:
        if request.POST.get('cancel'):
            return HttpResponseRedirect(reverse('slat:edp', args=(project_id)))

        if not edp.powercurve:
            form = EDP_PowerCurve_Form(request.POST)
        else:
            form = EDP_PowerCurve_Form(request.POST, instance=edp.powercurve)
        form.save()
        edp.powercurve = form.instance
        edp.flavour = EDP_Flavours.objects.get(pk=EDP_FLAVOUR_POWERCURVE);

        edp.save()
        edp._make_model()
        
        return HttpResponseRedirect(reverse('slat:edp_power', args=(project_id, edp_id)))
    else:
        if edp.powercurve:
            form = EDP_PowerCurve_Form(instance=edp.powercurve)
        else:
            form = EDP_PowerCurve_Form()

        return render(request, 'slat/edp_power_edit.html', {'form': form,
                                                            'project': project,
                                                            'edp': edp})

@login_required
def edp_userdef(request, project_id, edp_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    edp = get_object_or_404(EDP, pk=edp_id)
    charts = [IMDemandPlot(edp), DemandRatePlot(edp)]
    
    return render(request, 'slat/edp_userdef.html',
                  { 'project': project, 
                    'edp': edp,
                    'charts': charts,
                    'points': EDP_Point.objects.filter(demand=edp).order_by('im')})

@login_required
def edp_userdef_edit(request, project_id, edp_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    edp = get_object_or_404(EDP, pk=edp_id)
    
    if request.method == 'POST':
        if request.POST.get('cancel'):
            return HttpResponseRedirect(reverse('slat:edp_view', args=(project.id, edp.id)))

        edp.flavour =  EDP_Flavours.objects.get(pk=EDP_FLAVOUR_USERDEF);
        edp.interpolation_method = Interpolation_Method.objects.get(pk=request.POST.get('method'))
        edp.save()
        edp._make_model()
        
        Point_Form_Set = modelformset_factory(EDP_Point, can_delete=True, exclude=('demand',), widgets={'id': HiddenInput}, extra=3)
        formset = Point_Form_Set(request.POST, queryset=EDP_Point.objects.filter(demand=edp).order_by('im'))

        if not formset.is_valid():
            print(formset.errors)
        instances = formset.save(commit=False)
        
        for form in formset.deleted_forms:
            form.instance.delete()
            
        for instance in instances:
            if instance.id and instance.DELETE:
                instance.delete()
            else:
                instance.demand = edp
                instance.save()

        return HttpResponseRedirect(reverse('slat:edp_view', args=(project.id, edp.id)))
            
    # if a GET (or any other method) we'll create a blank form
    else:
        Point_Form_Set = modelformset_factory(EDP_Point, can_delete=True, exclude=('demand',), widgets={'id': HiddenInput}, extra=3)
        formset = Point_Form_Set(queryset=EDP_Point.objects.filter(demand=edp).order_by('im'))
        if edp.interpolation_method:
            form = Interpolation_Method_Form(initial={'method': edp.interpolation_method.id})
        else:
            form = Interpolation_Method_Form(initial={'method': INTERP_LINEAR})

        return render(request, 'slat/edp_userdef_edit.html',
                      {'form': form, 'points': formset,
                       'project': project, 'edp': edp})

@login_required
def edp_userdef_import(request, project_id, edp_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    edp = get_object_or_404(EDP, pk=edp_id)
    if request.method == 'POST':
        interp_form = Interpolation_Method_Form(request.POST)
        form = Input_File_Form(request.POST, request.FILES)

        try:
            if form.is_valid():
                if form.cleaned_data['flavour'].id == INPUT_FORMAT_CSV:
                    data = np.genfromtxt(request.FILES['path'].file, comments="#", delimiter=",", invalid_raise=True)
                    for d in data:
                        if type(d) == list or type(d) == np.ndarray:
                            for e in d:
                                if isnan(e):
                                    raise ValueError("Error importing data")
                        else:
                            if isnan(d):
                                raise ValueError("Error importing data")
                elif form.cleaned_data['flavour'].id == INPUT_FORMAT_LEGACY:
                    data = np.loadtxt(request.FILES['path'].file, skiprows=2)
                else:
                    raise ValueError("Unrecognised file format specified.")
            # Validate the data:
            points = [{'im': 0.0, 'mu': 0.0, 'sigma': 0.0}]
            for d in data:
                if len(d) < 2:
                    raise ValueError("Wrong number of columns")
                im = d[0]
                values = d[1:]
                ln_values = []
                nz_values = []
                for value in values:
                    if value != 0:
                        ln_values.append(log(value))
                        nz_values.append(value)
                median_edp = exp(np.mean(ln_values))
                sd_ln_edp = np.std(ln_values, ddof=1)
                points.append({'im': im, 'mu': median_edp, 'sigma': sd_ln_edp})

            edp.flavour = EDP_Flavours.objects.get(pk=EDP_FLAVOUR_USERDEF);
            if interp_form.is_valid():
                edp.interpolation_method = Interpolation_Method.objects.get(pk=interp_form.cleaned_data['method'])
            else:
                raise ValueError("INVALID INTERP FORM")
            edp.save()
            
            # Remove any existing points:
            EDP_Point.objects.filter(demand = edp).delete()
            
            # Insert new points:
            for p in points:
                EDP_Point(demand=edp, im=p['im'], median_x=p['mu'], sd_ln_x=p['sigma']).save()

            edp._make_model()
            return HttpResponseRedirect(reverse('slat:edp_userdef', args=(project_id, edp_id)))
        except ValueError as e:
            data = None
            form.add_error(None, 'There was an error importing the file.')

        #print(data)
        return render(request, 'slat/edp_userdef_import.html', {'form': form, 
                                                                'interp_form': interp_form,
                                                                'project': project,
                                                                'edp': edp,
                                                                'data': data})
            
    # if a GET (or any other method) we'll create a blank form
    else:
        if edp.interpolation_method:
            interp_form = Interpolation_Method_Form(initial={'method': edp.interpolation_method.id})
        else:
            interp_form = Interpolation_Method_Form()
        form = Input_File_Form()
        return render(request, 'slat/edp_userdef_import.html', {'form': form, 
                                                                'interp_form': interp_form,
                                                                'project': project,
                                                                'edp':edp})
    raise ValueError("EDP_USERDEF_IMPORT not implemented")

@login_required
def cgroup(request, project_id, floor_num, cg_id=None):
     project = get_object_or_404(Project, pk=project_id)

     if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

     if request.method == 'POST':
         if request.POST.get('cancel'):
             return HttpResponseRedirect(reverse('slat:edp', args=(project_id)))
         cg_form = CompGroupForm(request.POST)
         cg_form.save()
         cg_id = cg_form.instance.id
         
         return HttpResponseRedirect(reverse('slat:compgroup', args=(project_id, cg_id)))
     else:
         if cg_id:
             cg = get_object_or_404(Component_Group, pk=cg_id)
             cg_form = CompGroupForm(instance=cg)
         else:
             cg_form = CompGroupForm()
             
             
             
         return render(request, 'slat/cgroup.html', {'project_id': project_id,
                                                     'floor_num': floor_num, 
                                                     'cg_id': cg_id,
                                                     'cg_form': cg_form})

@login_required
def level_cgroup(request, project_id, level_id, cg_id=None):
     project = get_object_or_404(Project, pk=project_id)

     if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

     if request.method == 'POST':
         if request.POST.get('cancel'):
             return HttpResponseRedirect(reverse('slat:level_cgroups', args=(project_id, level_id)))

         if request.POST.get('separate'):
             cg = Component_Group.objects.get(pk=cg_id)
             cg.pattern = None
             cg.save()
             return HttpResponseRedirect(reverse('slat:level_cgroups', args=(project_id, level_id)))
         
         if request.POST.get('make_pattern'):
             cg = Component_Group.objects.get(pk=cg_id)
             pattern = Component_Group_Pattern(project=project, 
                                          component=cg.component, 
                                          quantity_x=cg.quantity_x,
                                          quantity_y=cg.quantity_y,
                                          quantity_u=cg.quantity_u,
                                          cost_adj=cg.cost_adj,
                                          comment=cg.comment)
             pattern.save()
             cg.pattern = pattern
             cg.save()
             return HttpResponseRedirect(reverse('slat:level_cgroups', args=(project_id, level_id)))
         
         if request.POST.get('delete'):
             cg = Component_Group.objects.get(pk=cg_id)
             for m in cg.model().Models().values():
                 project.model().RemoveCompGroup(m)
             cg.delete()
             if request.POST.get('next_url'):
                 return HttpResponseRedirect(request.POST.get('next_url'))
             else:
                 return HttpResponseRedirect(reverse('slat:level_cgroups', args=(project_id, level_id)))

         if cg_id:
             cg = Component_Group.objects.get(pk=cg_id)
             cg_form = FloorCompGroupForm(request.POST, initial=model_to_dict(cg))
         else:
             cg = Component_Group()
             cg_form = FloorCompGroupForm(request.POST)

         cg_form.is_valid()
         component = cg_form.cleaned_data['component']
         
         if re.search('^Accel(?i)', component.demand.name):
             demand_type = 'A'
         else:
             demand_type = 'D'

         try:
             edp = EDP_Grouping.objects.get(
                 project=project, 
                 level=Level.objects.get(pk=level_id),
                 type=demand_type)
         except:
             eprint("No demand found")
             
         changes = {'X': False, 'Y':False, 'U':False}
         if cg_id:
             if cg.demand != edp or \
                cg.component != component or \
                              cg.cost_adj != cg_form.cleaned_data['cost_adj']:
                 changes['X'] = True
                 changes['Y'] = True
                 changes['U'] = True
             
         if cg.quantity_x != cg_form.cleaned_data['quantity_x']:
             changes['X'] = True
         if cg.quantity_y != cg_form.cleaned_data['quantity_y']:
             changes['Y'] = True
         if cg.quantity_u != cg_form.cleaned_data['quantity_u']:
             changes['U'] = True
             
         cg.demand = edp
         cg.component = component
         cg.quantity_x = cg_form.cleaned_data['quantity_x']
         cg.quantity_y = cg_form.cleaned_data['quantity_y']
         cg.quantity_u = cg_form.cleaned_data['quantity_u']
         cg.cost_adj = cg_form.cleaned_data['cost_adj']
         cg.comment = cg_form.cleaned_data['comment']
         cg.save()
         if True in changes.values():
             cg._make_model(changes)
         cg_id = cg.id
         
         if request.POST.get('next_url'):
             return HttpResponseRedirect(request.POST.get('next_url'))
         else:
             return HttpResponseRedirect(reverse('slat:level_cgroups', args=(project_id, level_id)))
     else:
         if cg_id:
             cg = get_object_or_404(Component_Group, pk=cg_id)
             data = model_to_dict(cg)
             data['next_url'] = request.META.get('HTTP_REFERER')
             demand_form = ComponentForm(initial=data, level=level_id)
         else:
             demand_form = ComponentForm(level=level_id, 
                                         initial= {'component': None, 
                                                   'cost_adj': 1.0, 
                                                   'comment': '', 
                                                   'quantity_x': 0,
                                                   'quantity_y': 0,
                                                   'quantity_u': 0, 
                                                   'next_url': request.META.get('HTTP_REFERER')})
         return render(request, 'slat/level_cgroup.html', {'project': project,
                                                           'level': Level.objects.get(pk=level_id),
                                                           'cg_id': cg_id,
                                                           'demand_form': demand_form,
                                                           'cancel_url': request.META.get('HTTP_REFERER')})
     

@login_required
def edp_cgroups(request, project_id, edp_id):
    project = get_object_or_404(Project, pk=project_id)
    edp = get_object_or_404(EDP, pk=edp_id)
        
    if request.method == 'POST':
         raise ValueError("SHOULD NOT GET HERE")
    else:
        return render(request, 'slat/edp_cgroups.html',
                      {'project': project,
                       'edp': edp,
                       'cgs': Component_Group.objects.filter(demand=edp)})

@login_required
def edp_cgroup(request, project_id, edp_id, cg_id=None):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    edp = get_object_or_404(EDP, pk=edp_id)
    if request.method == 'POST':
        if request.POST.get('cancel'):
            return HttpResponseRedirect(reverse('slat:edp_cgroups', args=(project_id, edp_id)))

        if request.POST.get('delete'):
            cg = Component_Group.objects.get(pk=cg_id)
            project.model().RemoveCompGroup(cg.model())
            cg.delete()
            return HttpResponseRedirect(reverse('slat:edp_cgroups', args=(project_id, edp_id)))
             
        if cg_id:
             cg = Component_Group.objects.get(pk=cg_id)
        else:
             cg = None
        cg_form = EDPCompGroupForm(request.POST, instance=cg)
         
        cg_form.save(commit=False)
        if cg_id:
            cg_form.instance.id = int(cg_id)
        cg_form.save()
        if cg_form.has_changed():
            cg_form.instance._make_model()

        return HttpResponseRedirect(reverse('slat:edp_cgroups', args=(project_id, edp_id)))
    else:
        if cg_id:
            cg = Component_Group.objects.get(pk=cg_id)
            cg_form = EDPCompGroupForm(instance=cg)
        else:
            cg_form = EDPCompGroupForm(initial={'demand': edp})
        
        if edp.type == 'A':
            cg_form.fields['component'].queryset = ComponentsTab.objects.filter(demand=DemandsTab.objects.get(name__icontains='Accel'))
        elif edp.type == 'D':
            cg_form.fields['component'].queryset = ComponentsTab.objects.filter(demand=DemandsTab.objects.get(name__icontains='Drift'))
            
        return render(request, 'slat/edp_cgroup.html',
                      {'project': project,
                       'edp': edp,
                       'cg_form': cg_form})
    
@login_required
def cgroups(request, project_id, groups=None):
     project = get_object_or_404(Project, pk=project_id)
     cgs = []
     levels = []
     for cg in Component_Group_Pattern.objects.filter(project=project):
         key = {'component': cg.component, 
                'adj': cg.cost_adj,
                'count_x': cg.quantity_x,
                'count_y': cg.quantity_y,
                'count_u': cg.quantity_u,
                'comment': cg.comment,
                'id': cg.id,
                'level': None}
         if not key in cgs:
             cgs.append(key)
             levels.append([])
         
     for cg in Component_Group.objects.filter(demand__project=project).order_by("component"):
         key = {'component': cg.component, 
                'adj': cg.cost_adj,
                'count_x': cg.quantity_x,
                'count_y': cg.quantity_y,
                'count_u': cg.quantity_u,
                'comment': cg.comment,
                'id': cg.id if not cg.pattern else cg.pattern.id,
                'level': (None if cg.pattern != None else cg.demand.level)}
         if not key in cgs:
             cgs.append(key)
             levels.append([])

         index = cgs.index(key)
         levels[index].append(cg.demand.level)

     data = []
     raw_data = list(zip(cgs, levels))
     
     def sort_components(l):
          convert = lambda text: float(text) if text.isdigit() else text
          alphanum = lambda key: [ convert(c) for c in re.split('([-+]?[0-9]*\.?[0-9]*)', key[0]['component'].ident) ]
          l.sort( key=alphanum )
          return l
      
     raw_data = sort_components(raw_data)
     for x in raw_data:
         dict = x[0]
         dict['levels'] = x[1]
         data.append(dict)
     return render(request, 'slat/cgroups.html', {'project': project,
                                                  'data': data})
 
@login_required
def level_cgroups(request, project_id, level_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    edp_groups = EDP_Grouping.objects.filter(project=project, 
                                           level=Level.objects.get(pk=level_id)).order_by('type')
    cgs = []
    totals = {'X':0, 'Y':0, 'U':0}
    charts = {'A':{'X': None, 'Y':None}, 'D':{'X':None, 'Y':None}}
    charts2 = {'A': None, 'D': None}
    for group in edp_groups:
        charts[group.type]['X'] = DemandRatePlot(group.demand_x)
        charts[group.type]['Y'] = DemandRatePlot(group.demand_y)
        if group.type == 'A':
            charts2[group.type] = DemandRatesPlot1(group)
        else:
            charts2[group.type] = DemandRatesPlot2(group)
            
        groups = Component_Group.objects.filter(demand=group)
        for cg in groups:
            cgs.append(cg)
            cost = cg.model().Deaggregated_E_annual_cost()
            totals['X'] = totals['X'] + cost['X']
            totals['Y'] = totals['Y'] + cost['Y']
            totals['U'] = totals['U'] + cost['U']
            
    totals['composite'] = totals['X'] + totals['Y'] + totals['U']

    if request.method == 'POST':
         raise ValueError("SHOULD NOT GET HERE")
    else:
        return render(request, 'slat/level_cgroups.html',
                      {'project': project,
                       'level': Level.objects.get(pk=level_id),
                       'cgs': cgs,
                       'totals': totals,
                       'charts': charts, 'charts2': charts2})

@login_required
def levels(request, project_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    levels = project.levels()
    level_info = []
    for level in levels:
        accel_x = EDP_Grouping.objects.get(project=project, level=level, type='A').demand_x.flavour != None
        accel_y = EDP_Grouping.objects.get(project=project, level=level, type='A').demand_y.flavour != None
        if level.level < project.num_levels():
            drift_x = EDP_Grouping.objects.get(project=project, level=level, type='D').demand_x.flavour != None
            drift_y = EDP_Grouping.objects.get(project=project, level=level, type='D').demand_y.flavour != None
        else:
            drift_x = False
            drift_y = False
            
        level_info.append({'label': level.label,
                           'level': level,
                           'id': level.id,
                           'accel_x': accel_x, 
                           'accel_y': accel_y, 
                           'drift_x': drift_x,
                           'drift_y': drift_y})
    return render(request, 'slat/levels.html', 
                  {'project': project, 
                   'level_info': level_info,
                   'levels': levels})

@login_required
def demand(request, project_id, level_id, type, direction):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    if type == 'drift':
        type = 'D'
    elif type =='acceleration':
        type = 'A'
    else:
        raise ValueError("UNKNOWN DEMAND TYPE")
        
    demand_group = EDP_Grouping.objects.get(
        project=project,
        level=Level.objects.get(pk=level_id), 
        type=type)
    
    if direction == 'X':
        demand = demand_group.demand_x
    elif direction == 'Y':
        demand = demand_group.demand_y
    else:
        demand = None
        
    if demand == None:
        raise ValueError("Demand does not exist")

    flavour = demand.flavour
    if not flavour:
        return HttpResponseRedirect(reverse('slat:edp_choose', args=(project_id, demand.id)))
    elif flavour.id == EDP_FLAVOUR_POWERCURVE:
        return HttpResponseRedirect(reverse('slat:edp_power', args=(project_id, demand.id)))
    elif flavour.id == EDP_FLAVOUR_USERDEF:
        return HttpResponseRedirect(reverse('slat:edp_userdef', args=(project_id, demand.id)))
    else:
        raise ValueError("demand view not implemented")

    
@login_required
def analysis(request, project_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied
    
    job = Project_Basic_Analysis.delay(project_id)
    return render(request, 'slat/analysis.html', 
                  {'project': project, 
                   'task_id': job.id})

class ComponentAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        # Don't forget to filter out results depending on the visitor !
        #if not self.request.user.is_authenticated():
        #    return Country.objects.none()

        q = self.request.GET.get('q')

        qs = ComponentsTab.objects.all()

        category = self.forwarded.get('category', None)
        floor_num = self.forwarded.get('floor', None)
        
        if category:
            qs = qs.filter(ident__regex=category)

        if floor_num and int(floor_num)==0:
            acceleration = DemandsTab.objects.filter(name__icontains='Accel')[0]
            qs = qs.filter(demand=acceleration)

        if q:
            qs = qs.filter(Q(ident__iregex=q) | Q(name__iregex=q))
            
        return qs

@login_required
def ComponentDescription(request, component_key):
    component = ComponentsTab.objects.get(pk=component_key)
    result = render(request, 'slat/component-description.html', 
                    {'component': component,
                     'fragility': FragilityTab.objects.filter(component = component).order_by('state'),
                     'costs': CostTab.objects.filter(component = component).order_by('state')})
    return(result)

@login_required
def shift_level(request, project_id, level_id, shift):
    shift = int(shift)
    project = Project.objects.get(pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    level_to_move = Level.objects.get(pk=level_id)
    if project != level_to_move.project:
        print("HEY--WRONG PROJECT!")
    else:
        print("Project number is correct")
        
    if shift > 0:
        try:
            other_level = Level.objects.get(project=project, level=level_to_move.level + 1)
            level_to_move.level = level_to_move.level + 1
            other_level.level = other_level.level - 1
            level_to_move.save()
            other_level.save()
        except Level.DoesNotExist:
            print("Nowhere to go")
    elif shift < 0:
        try:
            other_level = Level.objects.get(project=project, level=level_to_move.level - 1)
            level_to_move.level = level_to_move.level - 1
            other_level.level = other_level.level + 1
            level_to_move.save()
            other_level.save()
        except Level.DoesNotExist:
            print("Nowhere to go")
    else:
        print("??????")
    return HttpResponseRedirect(reverse('slat:levels', args=(project_id,)))

@login_required
def rename_level(request, project_id, level_id):
    project = Project.objects.get(pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    level = Level.objects.get(pk=level_id)
    if request.method == 'POST':
        form = LevelLabelForm(request.POST)
        if form.is_valid():
            level.label = form.cleaned_data['label']
            level.save()
        return HttpResponseRedirect(reverse('slat:levels', args=(project_id)))
        
    else:
        form = LevelLabelForm(initial={'label': level.label})
        return render(request, 'slat/rename_label.html', {'project': project,
                                                          'level': level,
                                                          'form': form})
    
class SLATRegistrationView(RegistrationView):
    def __init__(self, *args, **kwargs):
        self.form_class = SLATRegistrationForm
        super(SLATRegistrationView, self).__init__(*args, **kwargs)
        
    def get_success_url(self, activateduser):
        return reverse('slat:index')

class SLATRegistrationForm(RegistrationForm):
    organization = CharField()
    first_name = CharField()
    last_name = CharField()
    
    def save(self, *args, **kwargs):
        user = super(SLATRegistrationForm, self).save(*args, **kwargs)
        if user:
            user.first_name = self.cleaned_data['first_name']
            user.last_name = self.cleaned_data['last_name']
            user.save()

            profile = Profile.objects.get(user=user)
            profile.organization = self.cleaned_data['organization']
            profile.save()
        return user

class ProjectAddUserForm(Form):
    userid = CharField()
    
@login_required
def project_add_user(request, project_id):
    project = Project.objects.get(pk=project_id)
    if not project.CanWrite(request.user):
        raise PermissionDenied

    if request.method == 'POST':
        form = ProjectAddUserForm(request.POST)
        form.is_valid()
        try:
            user = User.objects.get(username=form.cleaned_data['userid'])
            project.AssignRole(user, ProjectUserPermissions.ROLE_FULL)
            return HttpResponseRedirect(reverse('slat:project', args=(project_id,)))
        except:
            form.message = "User {} not found.".format(form.cleaned_data['userid'])
            return render(request, 'slat/project_add_user.html', context={'project_id': project_id, 'project': project, 'form': form})
            
    else:
        form = ProjectAddUserForm()
        return render(request, 'slat/project_add_user.html', context={'project_id': project_id, 'project': project, 'form': form})
    
class ProjectRemoveUserForm(Form):
    userid = CharField()
    
@login_required
def project_remove_user(request, project_id):
    project = Project.objects.get(pk=project_id)
    if not project.CanWrite(request.user):
        raise PermissionDenied

    if request.method == 'POST':
        form = ProjectRemoveUserForm(request.POST)
        form.is_valid()
        try:
            user = User.objects.get(username=form.cleaned_data['userid'])
            project.AssignRole(user, ProjectUserPermissions.ROLE_NONE)
            return HttpResponseRedirect(reverse('slat:project', args=(project_id,)))
        except:
            form.message = "User {} not found.".format(form.cleaned_data['userid'])
            return render(request, 'slat/project_remove_user.html', context={'project_id': project_id, 
                                                                             'project': project, 
                                                                             'form': form})
            
    else:
        form = ProjectRemoveUserForm()
        form.fields['userid'].widget = Select()
        users = []
        for permissions in ProjectUserPermissions.objects.filter(project=project, role=ProjectUserPermissions.ROLE_FULL):
            user = permissions.user
            if user != request.user:
                users.append([user.username, user.username])
        form.fields['userid'].widget.choices = users
        return render(request, 'slat/project_remove_user.html', context={'project_id': project_id,
                                                                         'project': project, 
                                                                         'form': form})

@login_required    
def group(request, group_id=None):
    if group_id:
        group = Group.objects.get(pk=group_id)
        if not group.IsMember(request.user):
            raise PermissionDenied
    else:
        group = None

        
    if request.method == 'POST':
        if group:
            form = GroupForm(request.POST,
                             group,
                             initial=model_to_dict(group))
            form.instance.id = group_id
        else:
            form = GroupForm(request.POST)

        if not group or form.has_changed():
            if not form.is_valid():
                print(form.errors)
                return render(request, 'slat/group.html', { 'group': group, 'form': form})
            else:
                form.save()
                group = form.instance
                if not group.IsMember(request.user):
                    group.AddMember(request.user)

        return HttpResponseRedirect(reverse('slat:group', args=(form.instance.id,)))
    else:
        if group:
            form = GroupForm(instance=group, initial=model_to_dict(group))
            members = []
            for user in User.objects.all():
                if group.IsMember(user):
                    members.append(user)
        else:
            form = GroupForm()
            members = None

    return render(request, 'slat/group.html', { 'group': group, 'members': members, 'form': form})

class GroupAddUserForm(Form):
    userid = CharField()
    
@login_required
def group_add_user(request, group_id):
    group = Group.objects.get(pk=group_id)

    if not group.IsMember(request.user):
        raise PermissionDenied

    if request.method == 'POST':
        form = GroupAddUserForm(request.POST)
        form.is_valid()
        try:
            user = User.objects.get(username=form.cleaned_data['userid'])
            group.AddMember(user)
            return HttpResponseRedirect(reverse('slat:group', args=(group_id,)))
        except:
            form.message = "User {} not found.".format(form.cleaned_data['userid'])
            return render(request, 'slat/group_add_user.html', context={'group_id':group.id, 'group': group, 'form': form})
            
    else:
        form = GroupAddUserForm()
        return render(request, 'slat/group_add_user.html', context={'group_id':group.id, 'group': group, 'form': form})
    
class GroupRemoveUserForm(Form):
    userid = CharField()
    
@login_required
def group_remove_user(request, group_id):
    group = Group.objects.get(pk=group_id)
    if not group.IsMember(request.user):
        raise PermissionDenied

    if request.method == 'POST':
        form = GroupRemoveUserForm(request.POST)
        form.is_valid()
        try:
            user = User.objects.get(username=form.cleaned_data['userid'])
            group.RemoveMember(user)
            if user == request.user:
                # User removed themselves from the group, so they
                # won't be able to see it anymore
                return HttpResponseRedirect(reverse('slat:index'))
            else:
                return HttpResponseRedirect(reverse('slat:group', args=(group_id,)))
        except:
            form.message = "User {} not found.".format(form.cleaned_data['userid'])
            return render(request, 'slat/group_remove_user.html', 
                          context={'groujp_id': group_id, 
                                   'group': group, 
                                   'form': form})
            
    else:
        form = GroupRemoveUserForm()
        form.fields['userid'].widget = Select()
        users = []
        for user in User.objects.all():
            if group.IsMember(user):
                users.append([user.username, user.username])
        form.fields['userid'].widget.choices = users
        return render(request, 'slat/group_remove_user.html', context={'group_id': group_id,
                                                                       'group': group,
                                                                       'form': form})

class ProjectAddGroupForm(Form):
    groupid = CharField()
    
@login_required
def project_add_group(request, project_id):
    project = Project.objects.get(pk=project_id)
    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    if request.method == 'POST':
        form = ProjectAddGroupForm(request.POST)
        form.is_valid()
        try:
            group = Group.objects.get(name=form.cleaned_data['groupid'])
            group.GrantAccess(project)
            return HttpResponseRedirect(reverse('slat:project', args=(project_id,)))
        except:
            form.message = "Group {} not found.".format(form.cleaned_data['groupid'])
            return render(request, 'slat/project_add_group.html', context={'project_id': project_id, 'project': project, 'form': form})
    else:
        form = ProjectAddGroupForm()
        return render(request, 'slat/project_add_group.html', context={'project_id': project_id, 'project': project, 'form': form})
    
class ProjectRemoveGroupForm(Form):
    groupid = CharField()
    
@login_required
def project_remove_group(request, project_id):
    project = Project.objects.get(pk=project_id)
    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    if request.method == 'POST':
        form = ProjectRemoveGroupForm(request.POST)
        form.is_valid()
        try:
            group = Group.objects.get(name=form.cleaned_data['groupid'])
            group.DenyAccess(project)
            return HttpResponseRedirect(reverse('slat:project', args=(project_id,)))
        except:
            form.message = "Group {} not found.".format(form.cleaned_data['groupid'])
            return render(request, 'slat/project_remove_group.html', 
                          context={'project_id': project_id, 
                                   'project': project, 
                                   'form': form})
            
    else:
        form = ProjectRemoveGroupForm()
        form.fields['groupid'].widget = Select()
        groups = []
        for permissions in ProjectGroupPermissions.objects.filter(project=project):
            group = permissions.group
            groups.append([group.name, group.name])
        form.fields['groupid'].widget.choices = groups
        return render(request, 'slat/project_remove_group.html',
                      context={'project_id': project_id,
                               'project': project, 
                               'form': form})

def password_change(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # Important!
            messages.success(request, 'Your password was successfully updated!')
            return HttpResponseRedirect(reverse('slat:index'))
    else:
        form = PasswordChangeForm(request.user)

    return render(request, 'slat/password_change.html', {
        'form': form
    })

def etabs_confirm(request, preprocess_id):
    preprocess_data = ETABS_Preprocess.objects.get(id=preprocess_id)
    if request.POST:
        preprocess_data.period_x = request.POST.get('Tx')
        preprocess_data.period_y = request.POST.get('Ty')

        if preprocess_data.period_x == 'Manual':
            preprocess_data.period_x = request.POST.get('Manual_Tx', 0)
        if preprocess_data.period_y == 'Manual':
            preprocess_data.period_y = request.POST.get('Manual_Ty', 0)
        if preprocess_data.period_x == "" or preprocess_data.period_y == "":
            return HttpResponseRedirect(reverse('slat:project', request))
        
        preprocess_data.hazard_period_source = request.POST.get('Period', 0)
        preprocess_data.hazard_manual_period = request.POST.get('Manual_Period', 0)
        
        preprocess_data.drift_case_x = request.POST.get('x_drift_case', 0)
        preprocess_data.drift_case_y = request.POST.get('y_drift_case', 0)
        preprocess_data.accel_case_x = request.POST.get('x_accel_case', 0)
        preprocess_data.accel_case_y = request.POST.get('y_accel_case', 0)
        preprocess_data.yield_strength = request.POST.get('yield_strength')
        preprocess_data.save()

        job = ImportETABS.delay(
            request.user.id,
            preprocess_data.id)
        return HttpResponseRedirect(
            reverse('slat:etabs_progress') + '?job=' + job.id)
    else:
        confirm_form = ETABS_Confirm_Form(preprocess_id=preprocess_id)
        confirm_form.fields['yield_strength'].initial = round(preprocess_data.yield_strength / 1000) # Convert to kN
        return render(request, 'slat/etabs_preprocess.html', 
                      {'preprocess_data': preprocess_data,
                       'confirm_form': confirm_form})


    
def etabs_progress(request):
    if 'job' in request.GET:
        job_id = request.GET['job']
        job = ImportETABS.AsyncResult(job_id)
        data = job.result or job.state
        context = {
            'data':data,
            'task_id':job_id,
        }
        return render(request,"slat/etabs_progress.html",context)

@login_required
def cgrouppattern(request, project_id, cg_id=None):
     project = get_object_or_404(Project, pk=project_id)

     if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

     if request.method == 'POST':
         if request.POST.get('delete'):
            cgp = Component_Group_Pattern.objects.get(pk=cg_id)
            for cg in Component_Group.objects.filter(pattern=cgp):
               for m in cg.model().Models().values():
                 project.model().RemoveCompGroup(m)
               cg.delete()
            cgp.delete()

            if request.POST.get('next_url'):
                return HttpResponseRedirect(request.POST.get('next_url'))
            else:
                return HttpResponseRedirect(reverse('slat:compgroups', args=(project_id, )))

         # component, quantity_x, quantity_y, quantity_u, cost_adj, comment
         demand_form = PatternForm(request.POST)
         demand_form.is_valid()
         component = demand_form.cleaned_data['component']
         quantity_x = demand_form.cleaned_data['quantity_x']
         quantity_y = demand_form.cleaned_data['quantity_y']
         quantity_u = demand_form.cleaned_data['quantity_u']
         cost_adj = demand_form.cleaned_data['cost_adj']
         comment = demand_form.cleaned_data['comment']

         if cg_id:
             cg = get_object_or_404(Component_Group_Pattern, pk=cg_id)
             cg.ChangePattern(component, quantity_x, quantity_y, quantity_u,
                              cost_adj, comment)
         else:
             cg = Component_Group_Pattern(project=project, 
                                          component=component, 
                                          quantity_x=quantity_x,
                                          quantity_y=quantity_y,
                                          quantity_u=quantity_u,
                                          cost_adj=cost_adj,
                                          comment=comment)
             cg.save()

         for l in project.levels():
             # If level is using the pattern, get its component group:
             group = Component_Group.objects.filter(
                 pattern=cg.id,
                 demand__level= l)
             if len(group) == 0:
                 group = None
             else:
                 group = group[0]
                 
             if request.POST.get(str(l.level)):
                 if not group:
                     cg.CreateFromPattern(l)
             elif group:
                 group.delete()
                    
                 
         cg.ChangePattern(component, quantity_x, quantity_y, quantity_u, cost_adj, comment)
         if request.POST.get('next_url'):
             return HttpResponseRedirect(request.POST.get('next_url'))
         else:
             return HttpResponseRedirect(reverse('slat:compgroups', args=(project_id, )))
             
     else:
         if cg_id:
             cg = get_object_or_404(Component_Group_Pattern, pk=cg_id)
             data = model_to_dict(cg)
             data['next_url']=request.META.get('HTTP_REFERER')
             pattern_form = PatternForm(initial=data)
         else:
             pattern_form = PatternForm(initial= {'component': None, 
                                                  'cost_adj': 1.0, 
                                                  'comment': '', 
                                                  'quantity_x': 0,
                                                  'quantity_y': 0,
                                                  'quantity_u': 0,
                                                  'next_url': request.META.get('HTTP_REFERER')})
         level_form = LevelCheckBoxForm(project, cg_id)
                 
         return render(request, 'slat/cgrouppattern.html',
                       {'project': project,
                        'pattern_form': pattern_form,
                        'level_form': level_form,
                        'cancel_url': request.META.get('HTTP_REFERER'),
                       })

     
@login_required
def floor_by_floor(request, project_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied

    project = Project.objects.get(pk=project_id)
    level_map = []
    for l in project.levels():
        this_level = {'label': l.label, 'id': l.id, 'components': []}
        groups = Component_Group.objects.filter(demand__level=l, demand__project=project)
        for g in groups:
            this_level['components'].append(g)
        level_map.append(this_level)
                    
    job = Project_Detailed_Analysis.delay(project_id)
    return render(request, 'slat/floor_by_floor.html',
                  {'project': project,
                   'level_map': level_map,
                   'task_id': job.id})


def test(request, project_id=None):
    if request.method == 'GET':
        if request.GET.get('job'):
            raise ValueError("HOW DID THIS HAPPEN?")
            return render(request, 'slat/test.html', {})
        else:
            job = Incremental_Test.delay(project_id)

            project = Project.objects.get(pk=project_id)
            level_map = []
            for l in project.levels():
                this_level = {'label': l.label, 'components': []}
                groups = Component_Group.objects.filter(demand__level=l, demand__project=project)
                for g in groups:
                    this_level['components'].append(g)
                level_map.append(this_level)
                    
            return render(request, 'slat/test.html', {'task_id': job.id, 'level_map': level_map})
    else:
        # This should never happen!
        raise(ValueError("POST not supported"))

@login_required
def project_demand_plots(request, project_id):
    project = get_object_or_404(Project, pk=project_id)

    if not project.GetRole(request.user) == ProjectUserPermissions.ROLE_FULL:
        raise PermissionDenied
    
    job = Project_Demand_Plots.delay(project_id)
    return render(request, 'slat/demand_plots.html', 
                  {'project': project, 
                   'task_id': job.id})

def generic_poll_state(request):
    """ A view to report the progress to the user """
    data = 'Fail'
    if request.is_ajax():
        if 'task_id' in request.POST.keys() and request.POST['task_id']:
            task_id = request.POST['task_id']
            task = AsyncResult(task_id)
            try:
                data = task.result or task.data
            except:
                data = None
        else:
            data = 'No task_id in the request'
    else:
        data = 'This is not an ajax request'
        
    json_data = json.dumps(data)
    return HttpResponse(json_data, content_type='application/json')


# Notify the Celery task when things change that may require remodelling.
@receiver(post_save, sender=Project)
@receiver(post_save, sender=IM)
@receiver(post_save, sender=Component_Group)
def queue_task(sender, instance, **kwargs):
    oc = str(type(instance))
    id = instance.id
    HandleChange.delay(object_class=oc, object_id=id)

@receiver(pre_delete, sender=Component_Group)
def queue_delete_task(sender, instance, **kwargs):
    project = instance.demand.project
    HandleChange.delay(object_class=str(type(project)), object_id=project.id)

