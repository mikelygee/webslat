import pyslat
import sys
import time
from scipy.optimize import fsolve, newton
from django.db import models
from django.forms import  ModelForm, BaseModelFormSet, Select, NumberInput, Textarea, TextInput, FloatField, FileInput, FileField, Form, ModelChoiceField, IntegerField, HiddenInput, CharField
from django.forms import Form, ChoiceField, Select
from slat.constants import *
from .nzs import *
from .component_models import *
from dal import autocomplete
from django.urls import get_script_prefix
from django.utils.safestring import mark_safe
from dal import forward
from django.contrib.auth.models import User
from django.db.models import CASCADE, PROTECT, SET_NULL, DO_NOTHING
from django.db.models.signals import post_save
from django.dispatch import receiver
import numpy as np
import re

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

class SLAT_db_Router(object):
    """
    A router to control all database operations on models in the WebSLAT application.
    """
    def __init__(self):
        self.component_db_tables = [
            'components_tab', 
            'cost_tab', 
            'demands_tab',
            'fragility_tab',
            'units_tab', 
            'pact_cats_tab']

        self.constant_db_tables = [
            'slat_location',
            'slat_edp_flavours',
            'slat_im_types',
            'slat_input_file_formats',
            'slat_interpolation_method']


    def db_for_read(self, model, **hints):
        """
        Attempts to read comp models go to comp_db.
        """
        if model._meta.db_table in self.component_db_tables:
            return 'components_db'
        elif model._meta.db_table in self.constant_db_tables:
            return 'constants_db'
        return 'default'

    def db_for_write(self, model, **hints):
        """
        Attempts to write comp models go to comp_db.
        """
        if model._meta.db_table in self.component_db_tables:
            return 'components_db'
        elif model._meta.db_table in self.constant_db_tables:
            return 'constants_db'
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        """
        Allow relations if a model in the comp app is involved.
        """
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        Make sure the comp app only appears in the 'comp_db'
        database.
        """
        return None
        
# Create your models here.
class Project(models.Model):
    FREQUENCY_CHOICES = (
        (1./20, u'20'),
        (1./25, u'25'),
        (1./50, u'50'),
        (1./100, u'100'),
        (1./250, u'250'),
        (1./500, u'500'),
        (1./1000, u'1000'),
        (1./2500, u'2000'),
        (1./2500, u'2500'),
    )

    title_text = models.CharField(max_length=50)
    description_text = models.CharField(max_length=200, blank=True)
    IM = models.ForeignKey('IM', on_delete=PROTECT, null=True, blank=True)
    rarity = models.FloatField(null=False, choices=FREQUENCY_CHOICES)
    mean_im_collapse = models.FloatField(null=True, blank=True)
    sd_ln_im_collapse = models.FloatField(null=True, blank=True)
    mean_cost_collapse = models.FloatField(null=True, blank=True)
    sd_ln_cost_collapse = models.FloatField(null=True, blank=True)
    mean_im_demolition = models.FloatField(null=True, blank=True)
    sd_ln_im_demolition = models.FloatField(null=True, blank=True)
    mean_cost_demolition = models.FloatField(null=True, blank=True)
    sd_ln_cost_demolition = models.FloatField(null=True, blank=True)

    def AssignRole(self, user, role):
        if role == ProjectUserPermissions.ROLE_NONE:
            try: 
                permissions = ProjectUserPermissions.objects.get(project=self, user=user)
                permissions.delete()
            except ProjectUserPermissions.DoesNotExist:
                # Do nothing; permission is already missing from table
                None
        else:
            try: 
                permissions = ProjectUserPermissions.objects.get(project=self, user=user)
            except ProjectUserPermissions.DoesNotExist:
                permissions = ProjectUserPermissions(project=self, user=user)
            finally:
                permissions.role = role
                permissions.save()

    def GetRole(self, user):
        try: 
            permissions = ProjectUserPermissions.objects.get(project=self, user=user)
            return permissions.role
        except ProjectUserPermissions.DoesNotExist:
            return ProjectUserPermissions.ROLE_NONE

    def CanRead(self, user):
        role = self.GetRole(user)
        if role != ProjectUserPermissions.ROLE_NONE:
            return True

        for group in Group.objects.all():
            if group.HasAccess(self) and group.IsMember(user):
                return True
        return False

    def CanWrite(self, user):
        role = self.GetRole(user)
        if role != ProjectUserPermissions.ROLE_NONE:
            return True

        for group in Group.objects.all():
            if group.HasAccess(self) and group.IsMember(user):
                return True
        return False

    def _make_model(self):
        structure = pyslat.structure(self.id)
        
        if self.mean_cost_collapse and self.sd_ln_cost_collapse:
            structure.setRebuildCost(
                pyslat.MakeLogNormalDist(
                    self.mean_cost_collapse, pyslat.LOGNORMAL_MU_TYPE.MEAN_X,
                    self.sd_ln_cost_collapse, pyslat.LOGNORMAL_SIGMA_TYPE.SD_LN_X))

        if self.mean_cost_demolition and self.sd_ln_cost_demolition:
            structure.setDemolitionCost(
                pyslat.MakeLogNormalDist(
                    self.mean_cost_demolition, pyslat.LOGNORMAL_MU_TYPE.MEAN_X,
                    self.sd_ln_cost_demolition, pyslat.LOGNORMAL_SIGMA_TYPE.SD_LN_X))
            
        for cg in Component_Group.objects.filter(demand__project = self):
            structure.AddCompGroup(cg.model())

    def model(self):
        if not pyslat.structure.lookup(self.id):
            self._make_model()
        return pyslat.structure.lookup(self.id)

    def levels(self):
        return list(Level.objects.filter(project=self).order_by('-level'))

    def num_levels(self):
        return max(0, len(self.levels()) - 1)
            
    def __str__(self):
        if self.IM:
            im = self.IM.id
        else:
            im = "<no IM>"

        return "{}. {}: {}; {} {} {} ".format(self.id, self.title_text, 
                                              self.description_text,
                                              im,
                                              self.num_levels(),
                                              self.rarity)

    def im_label(self):
        return self.IM.label()

    def floor_label(self,floor):
        level = Level.objects.get(project=self, level=floor)
        return level.label

class ProjectUserPermissions(models.Model):
    ROLE_FULL = 'O'
    ROLE_NONE = 'N'
    ROLE_CHOICES = {
        (ROLE_FULL, 'Full'),
        (ROLE_NONE, 'None'),
        }
    
    project = models.ForeignKey(Project, on_delete=CASCADE, blank=False, null=False)
    user = models.ForeignKey(User, on_delete=CASCADE, blank=False, null=False)
    role = models.CharField(max_length=1, choices=ROLE_CHOICES, default=ROLE_NONE)

class Group(models.Model):
    name = models.CharField(max_length=20, blank=False, null=False, unique=True)

    def IsMember(self, user):
        try:
            GroupMember.objects.get(group=self, user=user)
            return True
        except GroupMember.DoesNotExist:
            return False
        
    def AddMember(self, user):
        if not self.IsMember(user):
            GroupMember(group=self, user=user).save()
        else:
            print("Already in group")
            
    def RemoveMember(self, user):
        if self.IsMember(user):
            GroupMember.objects.get(group=self, user=user).delete()

    def HasAccess(self, project):
        try:
            ProjectGroupPermissions.objects.get(project=project, group=self)
            return True
        except ProjectGroupPermissions.DoesNotExist:
            return False
    
    def GrantAccess(self, project):
        if not self.HasAccess(project):
            ProjectGroupPermissions(project=project, group=self).save()
    
    def DenyAccess(self, project):
        if self.HasAccess(project):
            ProjectGroupPermissions.objects.get(project=project, group=self).delete()
            
class GroupMember(models.Model):
    group = models.ForeignKey(Group, on_delete=CASCADE, blank=False, null=False)
    user = models.ForeignKey(User, on_delete=CASCADE, blank=False, null=False)

class ProjectGroupPermissions(models.Model):
    project = models.ForeignKey(Project, on_delete=CASCADE, blank=False, null=False)
    group = models.ForeignKey(Group, on_delete=CASCADE, blank=False, null=False)

    
class Level(models.Model):
    project = models.ForeignKey(Project, on_delete=CASCADE, blank=False, null=False)
    level = models.IntegerField(blank=False, null=False)
    label = models.CharField(max_length=50, blank=False, null=False)

    def __str__(self):
        return "Level #{}: {}".format(self.level, self.label)

class IM_Types(models.Model):
    name_text = models.CharField(max_length=25)

    class Meta:
        managed = False
        db_table = 'slat_im_types'

    def __str__(self):
        return self.name_text

class NonLinearHyperbolic(models.Model):
    v_assy_float = models.FloatField(default=1221)
    im_asy_float = models.FloatField(default=29.8)
    alpha_float = models.FloatField(default=62.2)

    def __str__(self):
        return "NonLinearHyperbolic: {} {} {}".format(self.v_assy_float,
                                                      self.im_asy_float,
                                                      self.alpha_float)

class Input_File_Formats(models.Model):
    format_text = models.CharField(max_length=20)

    class Meta:
        managed = False
        db_table = 'slat_input_file_formats'
        
    def __str__(self):
        return self.format_text


class Interpolation_Method(models.Model):
    method_text = models.CharField(max_length=20)

    class Meta:
        managed = False
        db_table = 'slat_interpolation_method'
        
    def __str__(self):
        return self.method_text

class IM_Point(models.Model):
    hazard = models.ForeignKey('IM', on_delete=CASCADE, null=False)
    im_value = models.FloatField()
    rate = models.FloatField()

class Location(models.Model):
    location = models.CharField(max_length=128)
    z = models.FloatField()
    min_distance = models.FloatField(null = True)
    max_disstance = models.FloatField(null = True)
    
    class Meta:
        managed = False
        db_table = 'slat_location'

    def __str__(self):
        return(self.location)

class NZ_Standard_Curve(models.Model):
    SOIL_CLASS_A = 'A'
    SOIL_CLASS_B = 'B'
    SOIL_CLASS_C = 'C'
    SOIL_CLASS_D = 'D'
    SOIL_CLASS_E = 'E'
    SOIL_CLASS_CHOICES = (
        (SOIL_CLASS_A, 'A'),
        (SOIL_CLASS_B, 'B'),
        (SOIL_CLASS_C, 'C'),
        (SOIL_CLASS_D, 'D'),
        (SOIL_CLASS_E, 'E')
    )

    soil_class = models.CharField(max_length=1,
                                  choices=SOIL_CLASS_CHOICES,
                                  default=SOIL_CLASS_A)
    period = models.FloatField(default=1.5)
    location = models.ForeignKey(Location, on_delete=DO_NOTHING, null=False, db_constraint=False)

    class Meta:
        managed = True
        db_table = 'slat_nz_standard_curve'


class IM(models.Model):
    flavour = models.ForeignKey(IM_Types, on_delete=PROTECT, blank=False, null=False, default=IM_TYPE_INTERP, db_constraint=False)
    nlh = models.ForeignKey(NonLinearHyperbolic, on_delete=SET_NULL, null=True, blank=True)
    interp_method = models.ForeignKey(Interpolation_Method, on_delete=PROTECT, null=True, blank=True, db_constraint=False)
    nzs = models.ForeignKey(NZ_Standard_Curve, on_delete=SET_NULL, null=True, blank=True)

    def label(self):
        return "Spectral Acceleration (g)"
    
    def _make_model(self):
        try:
            project = Project.objects.get(IM=self)
        except:
            # Hazard hasn't been fully specified yet; don't plot
            return None

        if self.flavour.id == IM_TYPE_NLH:
            nlh = pyslat.detfn('<nlh>', 'hyperbolic', [self.nlh.alpha_float,
                                                    self.nlh.im_asy_float,
                                                    self.nlh.v_assy_float])
            im_func = pyslat.im(self.id, nlh)
            f = lambda x: im_func.getlambda(x[0]) - project.rarity
            xlimit = fsolve(f, 0.01)[0]
            im_func.set_plot_max(xlimit)
        elif self.flavour.id == IM_TYPE_INTERP:
            #
            data = IM_Point.objects.filter(hazard = self).order_by('im_value')
            x = []
            y = []
            for d in data:
                x.append(d.im_value)
                y.append(d.rate)
            if self.interp_method.id == INTERP_LOGLOG:
                method = 'loglog'
            elif self.interp_method.id == INTERP_LINEAR:
                method = 'linear'
            else:
                raise ValueError("ILLEGAL INTERPOLATION METHOD")
            
            im_func = pyslat.im(self.id, pyslat.detfn('<interpolated>', method, [x.copy(), y.copy()]))
            if y[-1] > project.rarity:
                im_func.set_plot_max(x[-1])
            else:
                f = lambda x: im_func.getlambda(x[0]) - project.rarity
                xlimit = fsolve(f, x[-2])[0]
                im_func.set_plot_max(xlimit)
        elif self.flavour.id == IM_TYPE_NZS:
            x = []
            y = []
            for r in R_defaults:
                y.append(1/r)
                x.append(C(self.nzs.soil_class,
                           self.nzs.period,
                           r, 
                           self.nzs.location.z,
                           self.nzs.location.min_distance))
            im_func = pyslat.im(self.id, pyslat.detfn('<nzs>', 'loglog', [x.copy(), y.copy()]))
            if y[-1] > project.rarity:
                im_func.set_plot_max(x[-1])
            else:
                f = lambda x: im_func.getlambda(x[0]) - project.rarity
                xlimit = fsolve(f, x[-2])[0]
                im_func.set_plot_max(xlimit)

        if project.mean_im_collapse and project.sd_ln_im_collapse:
            im_func.SetCollapse(
                pyslat.MakeLogNormalDist(
                    project.mean_im_collapse, pyslat.LOGNORMAL_MU_TYPE.MEAN_X,
                    project.sd_ln_im_collapse, pyslat.LOGNORMAL_SIGMA_TYPE.SD_LN_X))

        if project.mean_im_demolition and project.sd_ln_im_demolition:
            im_func.SetDemolition(
                pyslat.MakeLogNormalDist(
                    project.mean_im_demolition, pyslat.LOGNORMAL_MU_TYPE.MEAN_X,
                    project.sd_ln_im_demolition, pyslat.LOGNORMAL_SIGMA_TYPE.SD_LN_X))

    def model(self):
        if not pyslat.im.lookup(self.id):
            self._make_model()
        return pyslat.im.lookup(self.id)
            
    def __str__(self):
        return "IM: {} {} {} [{}]".format(self.flavour, self.nlh, self.interp_method, self.id)

class EDP_Flavours(models.Model):
    name_text = models.CharField(max_length=25)

    class Meta:
        managed = False
        db_table = 'slat_edp_flavours'

    def __str__(self):
        return self.name_text

class EDP_PowerCurve(models.Model):
    median_x_a = models.FloatField(default=0.1)
    median_x_b = models.FloatField(default=1.5)
    sd_ln_x_a = models.FloatField(default=0.5)
    sd_ln_x_b = models.FloatField(default=0)

class EDP(models.Model):
    project = models.ForeignKey(Project, on_delete=CASCADE, blank=False, null=False)
    level = models.ForeignKey(Level, on_delete=CASCADE, blank=False, null=False)
    EDP_TYPE_DRIFT = 'D'
    EDP_TYPE_ACCEL = 'A'
    EDP_TYPE_CHOICES = (
        (EDP_TYPE_DRIFT, 'Inter-story Drift'),
        (EDP_TYPE_ACCEL, 'Acceleration'))
    type = models.CharField(max_length=1, 
                            choices=EDP_TYPE_CHOICES);
    flavour = models.ForeignKey(EDP_Flavours, on_delete=PROTECT, blank=False, null=True, db_constraint=False)
    powercurve = models.ForeignKey(EDP_PowerCurve, on_delete=SET_NULL, null=True, blank=False)
    interpolation_method = models.ForeignKey(Interpolation_Method, on_delete=PROTECT, null=True, blank=False, db_constraint=False)

    def __str__(self):
        return "{} {}".format(self.level.label,
                              dict(EDP.EDP_TYPE_CHOICES)[self.type])

    def _make_model(self):
        if not self.flavour:
            # Use an all-NAN function for the EDP, so any components attached to it
            # will have a cost of NAN:x
            mu = pyslat.detfn('<powercurve-mu>', 'power law', [np.nan, np.nan])
            sigma = pyslat.detfn('<powercurve-sigma>', 'power law', [np.nan, np.nan])
            prob_func = pyslat.probfn('<probfn>', 'lognormal',
                                      [pyslat.LOGNORMAL_MU_TYPE.MEDIAN_X, mu],
                                      [pyslat.LOGNORMAL_SIGMA_TYPE.SD_LN_X, sigma]) 
            edp_func = pyslat.edp(self.id, self.project.IM.model(), prob_func)
            eprint("edp_func: {}".format(edp_func))
            eprint("  edp_func.plot_max: {}".format(edp_func.plot_max()))
            eprint("  edp_func(0): {}".format(edp_func.Mean(0)))
            exit
        elif self.flavour.id == EDP_FLAVOUR_POWERCURVE:
            mu = pyslat.detfn('<powercurve-mu>', 'power law', [self.powercurve.median_x_a,
                                                               self.powercurve.median_x_b])
            sigma = pyslat.detfn('<powercurve-sigma>', 'power law', [self.powercurve.sd_ln_x_a,
                                                                     self.powercurve.sd_ln_x_b])
            prob_func = pyslat.probfn('<probfn>', 'lognormal',
                                      [pyslat.LOGNORMAL_MU_TYPE.MEDIAN_X, mu],
                                      [pyslat.LOGNORMAL_SIGMA_TYPE.SD_LN_X, sigma]) 
            edp_func = pyslat.edp(self.id, self.project.IM.model(), prob_func)

            mean = edp_func.Mean(self.project.IM.model().plot_max())
            
            sigma =  edp_func.SD(self.project.IM.model().plot_max())
            f = lambda x: edp_func.getlambda(x[0]) - self.project.rarity
            xlimit = fsolve(f, edp_func.Mean(self.project.IM.model().plot_max())/2)[0]
            edp_func.set_plot_max(xlimit)
            
        elif self.flavour.id == EDP_FLAVOUR_USERDEF:
            #
            data = EDP_Point.objects.filter(demand = self).order_by('im')
            x = []
            mu = []
            sigma = []
            for d in data:
                x.append(d.im)
                mu.append(d.median_x)
                sigma.append(d.sd_ln_x)

            if self.interpolation_method.id == INTERP_LOGLOG:
                method = 'loglog'
            elif self.interpolation_method.id == INTERP_LINEAR:
                method = 'linear'
            else:
                raise ValueError("ILLEGAL INTERPOLATION METHOD")
            
            mu = pyslat.detfn('<interpolated-mu>', method, [x.copy(), mu.copy()])
            sigma = pyslat.detfn('<interpolated-sigma>', method, [x.copy(), sigma.copy()])

            prob_func = pyslat.probfn('<probfn>', 'lognormal',
                                      [pyslat.LOGNORMAL_MU_TYPE.MEDIAN_X, mu],
                                      [pyslat.LOGNORMAL_SIGMA_TYPE.SD_LN_X, sigma]) 
            edp_func = pyslat.edp(self.id, self.project.IM.model(), prob_func)

            mean = edp_func.Mean(self.project.IM.model().plot_max())
            sigma =  edp_func.SD(self.project.IM.model().plot_max())

            epsilon = 1E-2
            counter = 0
            low_x = 0
            low_y = edp_func.getlambda(low_x)


            high_x = edp_func.Median(self.project.IM.model().plot_max())
            high_y = edp_func.getlambda(high_x)
            old_high_y = None
            while high_y > self.project.rarity:
                high_x = high_x * 2
                old_high_y = high_y
                high_y = edp_func.getlambda(high_x)

                rate = (edp_func.getlambda(high_x) - edp_func.getlambda(high_x * (1.0 + epsilon)))/(epsilon * high_x)
                if rate < 1E-6:
                    break

            mid_x = high_x/2
            mid_y = edp_func.getlambda(mid_x)

            while counter < 100:
                counter = counter + 1
                xlimit = mid_x

                error = self.project.rarity - mid_y
                if abs(error) < self.project.rarity/10:
                    xlimit = mid_x
                    break
                elif error > 0:
                    high_x = mid_x
                    high_y = mid_y
                else:
                    low_x = mid_x
                    low_y = mid_y

                mid_x = (low_x + high_x)/2
                mid_y = edp_func.getlambda(mid_x)
                    
            edp_func.set_plot_max(xlimit)

    def model(self):
        if not pyslat.edp.lookup(self.id):
            self._make_model()
        return pyslat.edp.lookup(self.id)


class EDP_Point(models.Model):
    demand = models.ForeignKey('EDP', on_delete=CASCADE, null=False)
    im = models.FloatField()
    median_x = models.FloatField()
    sd_ln_x = models.FloatField()

    def __str__(self):
        return("Demand: {}; IM: {}; median_x: {}, sd_ln_x: {}".format(self.demand, self.im, self.median_x, self.sd_ln_x))
        return("an EDP_Point: [{}]".format(self.id))

class Component_Group(models.Model):
    demand = models.ForeignKey('EDP', on_delete=PROTECT, null=False)
    component = models.ForeignKey('ComponentsTab', on_delete=PROTECT, null=False, db_constraint=False)
    quantity = models.IntegerField(blank=False, null=False)
    cost_adj = models.FloatField(blank=False, null=False, default=1.0)
    comment = models.CharField(blank=True, null=True, max_length=256)

    def _make_model(self):
        frags = []
        for f in FragilityTab.objects.filter(component = self.component).order_by('state'):
            frags.append([f.median, f.beta])
        fragility = pyslat.fragfn_user(self.id, {'mu': pyslat.LOGNORMAL_MU_TYPE.MEDIAN_X,
                                                 'sd': pyslat.LOGNORMAL_SIGMA_TYPE.SD_LN_X},
                                       frags)

        costs = []
        for c in CostTab.objects.filter(component = self.component).order_by('state'):
            costs.append(pyslat.MakeBiLevelLoss(c.lower_limit, c.upper_limit,
                                                c.max_cost, c.min_cost,
                                                c.dispersion))
        cost = pyslat.bilevellossfn(self.id, costs)
        pyslat.compgroup(self.id, self.demand.model(), fragility, cost, None, self.quantity, 
                         self.cost_adj,
                         1.0  # delay adjustment factor
                         )

    def model(self):
        if not pyslat.compgroup.lookup(self.id):
            self._make_model()
        return pyslat.compgroup.lookup(self.id)
    

    def __str__(self):
        result = str(self.demand) + " "
        if self.component:
            result = result + str(self.component)
        else:
            result = result + "NO COMPONENT"
        result = result + " " + str(self.quantity)
        return result

    
class ProjectFormPart1(Form):
    def __init__(self, request=None, initial=None):
        super(Form, self).__init__(request, initial=initial)
        self.fields['description']=CharField(max_length=200, widget=Textarea(attrs={'cols': 50, 'rows': 4, 'title': "Enter the description"}))
        self.fields['title']=CharField(max_length=50, widget=TextInput(attrs={'title': 'Enter the title text here.'}))

class ProjectFormPart2(Form):
    def __init__(self, request=None, initial=None):
        super(Form, self).__init__(request, initial=initial)
        self.fields['rarity']= ChoiceField(
            widget=Select(
            attrs={'title': "The rate-of-exceedence of the rarest event we are interested in displaying."}),
                                           choices=Project.FREQUENCY_CHOICES)
        self.fields['levels'] = IntegerField()
        self.fields['mean_im_collapse'] = FloatField(widget=NumberInput(attrs={'title': 'The mean IM value at which collapse occurs.'}), required=False)
        self.fields['sd_ln_im_collapse'] = FloatField(widget=NumberInput(attrs={'title': 'The standard deviation of log(IM) at which collapse occurs.'}), required=False)
        self.fields['mean_cost_collapse'] = FloatField(widget=NumberInput(attrs={'title': 'The mean cost of collapse.'}), required=False)
        self.fields['sd_ln_cost_collapse'] = FloatField(widget=NumberInput(attrs={'title': 'The standard deviation of log(cost) of collapse.'}), required=False)
        self.fields['mean_im_demolition'] = FloatField(widget=NumberInput(attrs={'title': 'The mean IM value at which demolition occurs.'}), required=False)
        self.fields['sd_ln_im_demolition'] = FloatField(widget=NumberInput(attrs={'title': 'The standard deviation of log(IM) at which demolition occurs.'}), required=False)
        self.fields['mean_cost_demolition'] = FloatField(widget=NumberInput(attrs={'title': 'The mean cost of demolition.'}), required=False)
        self.fields['sd_ln_cost_demolition'] = FloatField(widget=NumberInput(attrs={'title': 'The standard deviation of log(cost) of demolition.'}), required=False)

class ProjectFormPart3(Form):
    FRAME_CHOICES = (
        ("Braced", "Braced"),
        ("Moment", "Moment"),
        ("Wall", "Wall"))
    
    def __init__(self, request=None, 
                 initial={'return_period': '500',
                          'strength': 1.0,
                          'soil_class': 'C',
                          'location': 'Christchurch',
                          'frame_type': 'Moment'}):
        super(ProjectFormPart3, self).__init__(request, initial=initial)
        self.fields['frame_type'].widget.attrs['title'] = 'The frame type of the structure.'
        self.fields['return_period'].label = 'Return period (years)'
        self.fields['return_period'].widget.attrs['title'] = 'The return period (years)'
        self.fields['strength'].widget.attrs['title'] = 'The strength ratio at the design level of spectral acceleration.'
        self.fields['path'].widget.attrs['title'] = 'The Excel file exported from ETABS.'
        self.fields['soil_class'].widget.attrs['title'] = 'The soil class at the building site.'
        self.fields['location'].widget.attrs['title'] = 'The location of the building site.'

    frame_type = ChoiceField(choices= FRAME_CHOICES)
    return_period = ChoiceField(choices=list(map(lambda x: [x, x], R_defaults)))
    strength = FloatField()
    path = FileField()
    soil_class = ChoiceField(choices=NZ_Standard_Curve.SOIL_CLASS_CHOICES)
    location_choices = []
    for location in Location.objects.all():
        location_choices.append([location.location, location.location])
    location = ChoiceField(choices=location_choices)
        
class ProjectForm(ModelForm):
    class Meta:
        model = Project
        fields = '__all__'
        
        widgets = {
            'description_text': Textarea(attrs={'cols': 50, 'rows': 4, 'title': "Enter the description"}),
            'IM': HiddenInput,
            'title_text': TextInput(attrs={'title': 'Enter the title text here.'}),
            'rarity': Select(attrs={'title': "The rate-of-exceedence of the rarest event we are interested in displaying."}),
            'mean_im_collapse': NumberInput(attrs={'title': 'The mean IM value at which collapse occurs.'}),
            'sd_ln_im_collapse': NumberInput(attrs={'title': 'The standard deviation of log(IM) at which collapse occurs.'}),
            'mean_cost_collapse': NumberInput(attrs={'title': 'The mean cost of collapse.'}),
            'sd_ln_cost_collapse': NumberInput(attrs={'title': 'The standard deviation of log(cost) of collapse.'}),
            'mean_im_demolition': NumberInput(attrs={'title': 'The mean IM value at which demolition occurs.'}),
            'sd_ln_im_demolition': NumberInput(attrs={'title': 'The standard deviation of log(IM) at which demolition occurs.'}),
            'mean_cost_demolition': NumberInput(attrs={'title': 'The mean cost of demolition.'}),
            'sd_ln_cost_demolition': NumberInput(attrs={'title': 'The standard deviation of log(cost) of demolition.'}),
            }

class LevelsForm(Form):
    def __init__(self, request=None, initial=None):
        super(Form, self).__init__(request, initial=initial)
        self.fields['levels'] = IntegerField()
        
        
class HazardForm(ModelForm):
    def __init__(self, instance=None, initial=None):
        super(HazardForm, self).__init__(instance=instance, initial=initial)
        self.fields['flavour'].label='Hazard Definition Type'
        self.fields['flavour'].widget.attrs['title'] ='Choose how to specify the hazard curve.'
        
    class Meta:
        model = IM
        fields = '__all__'
        widgets = {
            'nlh': HiddenInput,
            'interp_method': HiddenInput,
            'nzs': HiddenInput
            }

class NLHForm(ModelForm):
    def __init__(self, request=None, instance=None):
        super(NLHForm, self).__init__(request, instance=instance)
        self.fields['v_assy_float'].widget.attrs['class'] = 'normal'
        self.fields['im_asy_float'].widget.attrs['class'] = 'normal'
        self.fields['alpha_float'].widget.attrs['class'] = 'normal'
        self.fields['v_assy_float'].widget.attrs['title'] = "v_assy"
        self.fields['im_asy_float'].widget.attrs['title'] = 'im_asy'
        self.fields['alpha_float'].widget.attrs['title'] = 'alpha'

    class Meta:
        model = NonLinearHyperbolic
        fields = '__all__'

class Interpolation_Method_Form(Form):
    def __init__(self, request=None, initial=None):
        super(Interpolation_Method_Form, self).__init__(request, initial=initial)
        self.fields['method'].widget.attrs['class'] = 'normal'
        self.fields['method'].widget.attrs['title'] = 'Choose the interpolation method.'

    def choices():
        objects = []
        for method in Interpolation_Method.objects.all():
            objects.append([method.id, method.method_text])
        return objects

    method = ChoiceField(choices=choices, label='Interpolation Method')
    
class EDPForm(ModelForm):
    class Meta:
        model = EDP
        fields = ['flavour']

class EDP_PowerCurve_Form(ModelForm):
    class Meta:
        model = EDP_PowerCurve
        fields = '__all__'
        
class Input_File_Form(Form):
    def __init__(self, post=None, files=None):
        super(Input_File_Form, self).__init__(post, files)
        self.fields['path'].widget.attrs['class'] = 'normal'
        self.fields['path'].widget.attrs['title'] = 'Choose the data file to read.'
        self.fields['flavour'].widget.attrs['class'] = 'normal'
        self.fields['flavour'].widget.attrs['title'] = 'Select the file format.'
        self.fields['flavour'].label = 'File Format'

    path = FileField()
    flavour = ModelChoiceField(queryset=Input_File_Formats.objects, empty_label=None)

class NZSForm(ModelForm):
    class Meta:
        model = NZ_Standard_Curve
        fields = '__all__'

class FloorsForm(Form):
    floors = IntegerField(initial=4)

class CompGroupForm(ModelForm):
    class Meta:
        model = Component_Group
        fields = '__all__'

class EDPCompGroupForm(ModelForm):
    class Meta:
        model = Component_Group
        fields = '__all__'
        widgets = {
            'demand': HiddenInput
        }

class FloorCompGroupForm(Form):
    component = ModelChoiceField(queryset=ComponentsTab.objects)
    quantity = IntegerField(initial=1)
    cost_adj = FloatField()
    comment = CharField(required=False)
        
def ListOfComponentCategories():
    demands = [[r"", "All"], ["^[0-9]", "SLAT"], ["^[A-Z]", "PACT"]]
    for d in PACT_CatsTab.objects.all():
        #if len(ComponentsTab.objects.filter(ident__regex=d.ident)) > 0:
        demands.append((d.ident, mark_safe(len(d.ident) * "&nbsp;" + str(d))))
    return demands
    

class ComponentForm(Form):
    def __init__(self, initial=None, level=None):
        super(ComponentForm, self).__init__(initial)
        if initial:
            self.fields['component'].initial = initial['component']
        self.fields['component'].widget.forward.append(forward.Const(level, 'level'))
        self.fields['quantity'].widget.attrs['class'] = 'normal'
        self.fields['cost_adj'].widget.attrs['class'] = 'normal'
        self.fields['comment'].widget.attrs['comment'] = 'normal'
        self.fields['category'].widget.attrs['class'] = 'normal'
        self.fields['component'].widget.attrs['class'] = 'normal'
        self.fields['quantity'].widget.attrs['title'] = 'How many of this component are in the group?'
        self.fields['cost_adj'].widget.attrs['title'] = 'Adjustment factor from standard cost.'
        self.fields['comment'].widget.attrs['title'] = 'Notes about this component.'
        self.fields['category'].widget.attrs['title'] = 'Narrow the component search by category.'
        self.fields['component'].widget.attrs['title'] = 'Choose the type of component.'
        
    quantity = IntegerField()
    cost_adj = FloatField()
    comment = CharField(max_length=256, required=False)
    category = ChoiceField(choices=ListOfComponentCategories, required=False)
    component = ModelChoiceField(
        queryset=ComponentsTab.objects.all(),
        widget=autocomplete.Select2(url='/slat/component-autocomplete/',
                                    forward=['category']))

class LevelLabelForm(Form):
    def __init__(self, request=None, initial=None):
        super(Form, self).__init__(request, initial=initial)
        self.fields['label'].widget.attrs['class'] = 'normal'
        self.fields['label'].widget.attrs['title'] = 'Set the label for the level.'
        
    label = CharField()



class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    organization = models.CharField(max_length=30, blank=True)

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.profile.save()
    

class ProfileForm(ModelForm):
    class Meta:
        model = Profile
        fields = ('organization',)    

class GroupForm(ModelForm):
    class Meta:
        model = Group
        fields = '__all__'
        
