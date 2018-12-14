import pyslat
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import fsolve
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.forms import modelformset_factory, ValidationError, HiddenInput
from django.forms import formset_factory, BaseFormSet
from .nzs import *
from math import *
from  .models import *
from .component_models import *
from slat.constants import *
import os

def components(request):
    components_list = ComponentsTab.objects.all()
    context = { 'components_list': components_list }
    return render(request, 'slat/components.html', context)

def component(request, component_id):
    c = ComponentsTab.objects.get(ident=component_id)
    f = FragilityTab.objects.filter(component = c)
    costs = CostTab.objects.filter(component = c)
    context = {'component': c, 'fragility': f, 'costs': costs }
    return render(request, 'slat/component.html', context)

class CostFormSet(BaseModelFormSet):
     def cleanx(self):
         """Make sure the forms are consistent"""
         eprint("> CostFormSet::clean()")
         if any(self.errors):
             # Don't bother validating the formset unless each form is valid on its own
             eprint("< CostFormSet::clean() failing")
             return

         for i in range(0, len(self.forms) -1):
             eprint(i)
         eprint("< CostFormSet::clean() success")

class FragilityFormSet(BaseModelFormSet):
     def is_validx(self):
         eprint("> is_valid()")
         eprint(self.can_delete)
         if not self.is_bound:
             return False
         
         for f in self.forms[:-1]:
             eprint(self._should_delete_form(f))

         return True
         
     def cleanx(self):
         """Checks that no two articles have the same title."""
         eprint("> FragilityFormSet::clean()")
         valid = True
         for i, f in enumerate(self.forms[:-1]):
             eprint("form #{}: {}".format(i, f.is_valid()))
             if not f.is_valid():
                 valid = False
                 break
                    
         if not valid:
             # Don't bother validating the formset unless each form is valid on its own
             eprint("< FragilityFormSet::clean() failing")
             return
         eprint("< FragilityFormSet::clean() success")
         
def edit_component(request, component_id=None):
    #Cost_Form_Set = formset_factory(Cost_Form, CostFormSet, extra=1)
    Cost_Form_Set = modelformset_factory(CostTab, Cost_Form, formset=CostFormSet, extra=1)
    #Fragility_Form_Set = modelformset_factory(FragilityTab, Fragility_Form, extra=1)
    Fragility_Form_Set = modelformset_factory(FragilityTab, Fragility_Form, formset=FragilityFormSet, extra=1)

    if request.method == 'GET':
        if component_id:
            c = ComponentsTab.objects.get(pk=component_id)
            f = FragilityTab.objects.filter(component = c)
            costs = CostTab.objects.filter(component = c)
            cf = Component_Form(instance=c)

            
            cost_form_set = Cost_Form_Set(
                queryset=CostTab.objects.filter(component = c).order_by('state'))

            for i in cost_form_set:
                for field in ['min_cost', 'max_cost', 'lower_limit', 'upper_limit', 'dispersion']:
                    i[field].field.widget.attrs['style'] = 'text-align:right'

            fragility_form_set = Fragility_Form_Set(
                queryset=FragilityTab.objects.filter(component = c).order_by('state'))

            for i in fragility_form_set:
                for field in ['median', 'beta']:
                    i[field].field.widget.attrs['style'] = 'text-align:right'

        else:
            # Generate a blank form for creating a component
            cf = Component_Form()
            cost_form_set = Cost_Form_Set(queryset=CostTab.objects.none())
            fragility_form_set = Fragility_Form_Set(queryset=FragilityTab.objects.none())
            #eprint("cost_form_set: {}".format(dir(cost_form_set)))
            #eprint("cost_form_set.forms: {}".format(cost_form_set.forms))
            #for form in cost_form_set.forms:
            #    eprint("State: {}".format(form.instance.state))
            #eprint("-----------")
    else:
        if request.POST.get('cancel'):
            eprint("CANCEL!")
            if component_id:
                return HttpResponseRedirect(
                    reverse(
                        'slat:edit_component', 
                        args=(component_id,)))
            else:
                return HttpResponseRedirect(
                    reverse('slat:edit_component'))

        # POST request; process data
        if component_id:
            print("Change component")
            #for r in request.POST:
            #    eprint("{}: {}".format(r, request.POST[r]))
            #eprint("POST: {}".format(request.POST))
                
            c = ComponentsTab.objects.get(key=component_id)
            f = FragilityTab.objects.filter(component = c)
            costs = CostTab.objects.filter(component = c)
            cf = Component_Form(request.POST, instance=c)

            cost_form_set = Cost_Form_Set(
                request.POST,
                queryset=CostTab.objects.filter(component = c).order_by('state'))
            eprint("# cost forms: {}".format(len(cost_form_set)))
            for cost_form in cost_form_set:
                cost_form.instance.component = c
                eprint(cost_form.is_valid())
                eprint(cost_form.cleaned_data)
                #for f in cost_form.fields:
                #    eprint("{:10}: {}".format(f, cost_form.fields[f]))

            fragility_form_set = Fragility_Form_Set(
                request.POST,
                queryset=FragilityTab.objects.filter(component = c).order_by('state'))
            for fragility_form in fragility_form_set:
                fragility_form.instance.component = c
                eprint(fragility_form.instance)

            if not cf.is_valid() or not cost_form_set.is_valid() or not fragility_form_set.is_valid():
                eprint("IS VALID: {} {} {}".format(cf.is_valid(), cost_form_set.is_valid(), fragility_form_set.is_valid()))

                cost_form_set.forms.append(cost_form_set.empty_form)
                fragility_form_set.forms.append(fragility_form_set.empty_form)
                n = len(cost_form_set.forms)
                cost_form_set.forms[n - 1]['state'].initial = n
                cost_form_set.forms[n - 1]['min_cost'].initial = 0
                cost_form_set.forms[n - 1]['max_cost'].initial = 0
                cost_form_set.forms[n - 1]['lower_limit'].initial = 0
                cost_form_set.forms[n - 1]['upper_limit'].initial = 0
                cost_form_set.forms[n - 1]['dispersion'].initial = 0
                fragility_form_set.forms[n - 1]['state'].initial = n
                fragility_form_set.forms[n - 1]['description'].initial = ""
                fragility_form_set.forms[n - 1]['repairs'].initial = ""
                fragility_form_set.forms[n - 1]['median'].initial = 0
                fragility_form_set.forms[n - 1]['beta'].initial = 0
                fragility_form_set.forms[n - 1]['image'].initial = None

                if component_id:
                    c = ComponentsTab.objects.get(pk=component_id)
                    cost_form_set.forms[n - 1]['component'].initial = c
                    fragility_form_set.forms[n - 1]['component'].initial = c


                context = { 'component_form': cf,
                            'cost_form': cost_form_set,
                            'fragility_form': fragility_form_set}
                return render(request, 'slat/edit_component.html', context)
                
            else:
                if component_id:
                    cf.instance.key = component_id

                if cf.has_changed():
                    eprint("FORM CHANGED")
                    if 'ident' in cf.changed_data:
                        eprint("ident changed")
                        old_ident = ComponentsTab.objects.get(key=cf.instance.key).ident
                        new_ident = cf.instance.ident
                        # If there is an image directory, rename it
                        try:
                            eprint("CWD: {}".format(os.getcwd()))
                            old_path = os.path.join("static/slat/images", old_ident) 
                            new_path = os.path.join("static/slat/images", new_ident)
                            if os.path.exists(old_path):
                                eprint("Renaming {} --> {}".format(old_path, new_path))
                                os.rename(old_path, new_path)
                                eprint("Renamed successfully")
                                
                                old_path = os.path.join("slat/static/slat/images", old_ident) 
                                new_path = os.path.join("slat/static/slat/images", new_ident)
                                eprint("Renaming {} --> {}".format(old_path, new_path))
                                os.rename(old_path, new_path)
                                eprint("Renamed successfully")
                            else:
                                eprint("No image directory; nothing to rename")
                        except Exception as e:
                            eprint("Caught exception {}".format(e))
                            
                else:
                    eprint("No changes")

                cf.save()

                for cost_form in cost_form_set:
                    if cost_form.has_changed():
                        cost_form.save()

                if cost_form_set.has_changed():
                    eprint("COSTS CHANGED")
                else:
                    eprint("NO COST CHANGES")

                for index, fragility_form in enumerate(fragility_form_set):
                    if fragility_form.has_changed():
                        eprint("fragility form changed: {}".format(fragility_form.changed_data))
                        if 'image' in fragility_form.changed_data:
                            old_image = FragilityTab.objects.get(rowid=fragility_form.instance.rowid).image
                            new_image = fragility_form.instance.image

                            data = request.FILES.get("image-{}".format(index + 1))
                            data = data and data.read()
                            ident = cf.instance.ident
                            directory = os.path.join("slat/static/slat/images", ident)
                            if not os.path.exists(directory):
                                os.mkdirs(directory)
                                # Should we delete the old image?
                                if data:
                                    file.open(os.path.join(directory, new_image), "w").write(data)
                            
                            directory = os.path.join("static/slat/images", ident)
                            if not os.path.exists(directory):
                                os.mkdirs(directory)
                                # Should we delete the old image?
                                if data:
                                    file.open(os.path.join(directory, new_image), "w").write(data)
                        fragility_form.save()
                        
                if fragility_form_set.has_changed():
                    eprint("FRAGILITY CHANGED")
                else:
                    eprint("NO FRAGILITY CHANGES")

        else:
            print("Create component")
            cf = Component_Form()
            cost_form_set = None
            fragility_form_set = None


        if component_id:
            return HttpResponseRedirect(
                reverse(
                    'slat:edit_component', 
                    args=(component_id,)))
        else:
            return HttpResponseRedirect(
                reverse('slat:edit_component'))
    
    n = len(cost_form_set.forms)
    cost_form_set.forms[n - 1]['state'].initial = n
    cost_form_set.forms[n - 1]['min_cost'].initial = 0
    cost_form_set.forms[n - 1]['max_cost'].initial = 0
    cost_form_set.forms[n - 1]['lower_limit'].initial = 0
    cost_form_set.forms[n - 1]['upper_limit'].initial = 0
    cost_form_set.forms[n - 1]['dispersion'].initial = 0
    fragility_form_set.forms[n - 1]['state'].initial = n
    fragility_form_set.forms[n - 1]['description'].initial = ""
    fragility_form_set.forms[n - 1]['repairs'].initial = ""
    fragility_form_set.forms[n - 1]['median'].initial = 0
    fragility_form_set.forms[n - 1]['beta'].initial = 0
    fragility_form_set.forms[n - 1]['image'].initial = None

    if component_id:
        c = ComponentsTab.objects.get(pk=component_id)
        cost_form_set.forms[n - 1]['component'].initial = c
        fragility_form_set.forms[n - 1]['component'].initial = c
    

    context = { 'component_form': cf,
                'cost_form': cost_form_set,
                'fragility_form': fragility_form_set}
    return render(request, 'slat/edit_component.html', context)

