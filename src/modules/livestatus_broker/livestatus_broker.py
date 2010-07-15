#!/usr/bin/python
#Copyright (C) 2009 Gabes Jean, naparuba@gmail.com
#
#This file is part of Shinken.
#
#Shinken is free software: you can redistribute it and/or modify
#it under the terms of the GNU Affero General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.
#
#Shinken is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU Affero General Public License for more details.
#
#You should have received a copy of the GNU Affero General Public License
#along with Shinken.  If not, see <http://www.gnu.org/licenses/>.


#This Class is a plugin for the Shinken Broker. It is in charge
#to brok information of the service perfdata into the file
#var/service-perfdata
#So it just manage the service_check_return
#Maybe one day host data will be usefull too
#It will need just a new file, and a new manager :)

import time
import select
import socket
import sys
import cPickle

from host import Host
from hostgroup import Hostgroup
from service import Service
from servicegroup import Servicegroup
from contact import Contact
from contactgroup import Contactgroup
from timeperiod import Timeperiod
from command import Command
from config import Config
from livestatus import LiveStatus



#Class for the Livestatus Broker
#Get broks and listen to livestatus query language requests
class Livestatus_broker:
    def __init__(self, name, host, port, socket):
        self.host = host
        self.port = port
        self.socket = socket
        self.name = name
        
        #Warning :
        #self.properties will be add by the modulesmanager !!
        

    #Called by Broker so we can do init stuff
    #TODO : add conf param to get pass with init
    #Conf from arbiter!
    def init(self):
        print "I am init"
        self.q = self.properties['to_queue']
    
        #Our datas
        self.configs = {}
        self.hosts = {}
        self.services = {}
        self.contacts = {}
        self.hostgroups = {}
        self.servicegroups = {}
        self.contactgroups = {}
        self.timeperiods = {}
        self.commands = {}

        self.hostname_lookup_table = {}
        self.servicename_lookup_table = {}

        self.livestatus = LiveStatus(self.configs, self.hosts, self.services, self.contacts, self.hostgroups, self.servicegroups, self.contactgroups, self.timeperiods, self.commands)

        self.number_of_objects = 0
    

    def is_external(self):
        return True


    def get_name(self):
        return self.name


    #Get a brok, parse it, and put in in database
    #We call functions like manage_ TYPEOFBROK _brok that return us queries
    def manage_brok(self, b):
        type = b.type
        manager = 'manage_'+type+'_brok'
        #print "------------------------------------------- i receive", manager
        if hasattr(self, manager):
            #print "------------------------------------------- i manage", manager
            #print b
            f = getattr(self, manager)
            f(b)


    def manage_program_status_brok(self, b):
        data = b.data
        c_id = data['instance_id']
        #print "Creating config:", c_id, data
        c = Config()
        for prop in data:
            setattr(c, prop, data[prop])
        #print "CFG:", c
        self.configs[c_id] = c


    def manage_initial_host_status_brok(self, b):
        data = b.data
        h_id = data['id']
        #print "Creating host:", h_id, data
        h = Host({})
        for prop in data:
            setattr(h, prop, data[prop])

        h.check_period = self.get_timeperiod(h.check_period)
        h.notification_period = self.get_timeperiod(h.notification_period)
        
        h.contacts = self.get_contacts(h.contacts)

        #Escalations is not use for status_dat
        del h.escalations
                
        h.service_ids = []
        h.services = []
        self.hosts[h_id] = h
        self.hostname_lookup_table[h.host_name] = h_id
        self.number_of_objects += 1


    def manage_initial_hostgroup_status_brok(self, b):
        data = b.data
        hg_id = data['id']
        members = data['members']
        del data['members']
        #print "Creating hostgroup:", hg_id, data
        hg = Hostgroup()
        for prop in data:
            setattr(hg, prop, data[prop])
        setattr(hg, 'members', [])
        for (h_id, h_name) in members:
            if h_id in self.hosts:
                hg.members.append(self.hosts[h_id])
        #print "HG:", hg
        self.hostgroups[hg_id] = hg
        self.number_of_objects += 1


    def manage_initial_service_status_brok(self, b):
        data = b.data
        s_id = data['id']
        #print "Creating Service:", s_id, data
        s = Service({})
        self.update_element(s, data)

        s.check_period = self.get_timeperiod(s.check_period)
        s.notification_period = self.get_timeperiod(s.notification_period)

        s.contacts = self.get_contacts(s.contacts)

        del s.escalations

        h = self.find_host(data['host_name'])
        if h != None:
            # Reconstruct the connection between hosts and services
            h.service_ids.append(s_id)
            h.services.append(s)
            # There is already a s.host_name, but a reference to the h object can be useful too
            s.host = h
        self.services[s_id] = s
        self.servicename_lookup_table[s.host_name + s.service_description] = s_id
        self.number_of_objects += 1



    def manage_initial_servicegroup_status_brok(self, b):
        data = b.data
        sg_id = data['id']
        members = data['members']
        del data['members']
        #print "Creating servicegroup:", sg_id, data
        sg = Servicegroup()
        for prop in data:
            setattr(sg, prop, data[prop])
        setattr(sg, 'members', [])
        for (s_id, s_name) in members:
            if s_id in self.services:
                sg.members.append(self.services[s_id])
        #print "SG:", sg
        self.servicegroups[sg_id] = sg
        self.number_of_objects += 1


    def manage_initial_contact_status_brok(self, b):
        data = b.data
        c_id = data['id']
        #print "Creating Contact:", c_id, data
        c = Contact({})
        self.update_element(c, data)
        
        
        #print "C:", c
        self.contacts[c_id] = c
        self.number_of_objects += 1


    def manage_initial_contactgroup_status_brok(self, b):
        data = b.data
        cg_id = data['id']
        members = data['members']
        del data['members']
        print "Creating contactgroup:", cg_id, data
        cg = Contactgroup()
        for prop in data:
            setattr(cg, prop, data[prop])
        setattr(cg, 'members', [])
        for (c_id, c_name) in members:
            if c_id in self.contacts:
                cg.members.append(self.contacts[c_id])
        print "CG:", cg
        self.contactgroups[cg_id] = cg
        self.number_of_objects += 1


    def manage_initial_timeperiod_status_brok(self, b):
        data = b.data
        tp_id = data['id']
        print "Creating Timeperiod:", tp_id, data
        tp = Timeperiod({})
        self.update_element(tp, data)
        print "TP:", tp
        self.timeperiods[tp_id] = tp
        self.number_of_objects += 1


    def manage_initial_command_status_brok(self, b):
        data = b.data
        c_id = data['id']
        print "Creating Command:", c_id, data
        c = Command({})
        self.update_element(c, data)
        print "CMD:", c
        self.commands[c_id] = c
        self.number_of_objects += 1


    #A service check have just arrived, we UPDATE data info with this
    def manage_service_check_result_brok(self, b):
        data = b.data
        s = self.find_service(data['host_name'], data['service_description'])
        if s != None:
            self.update_element(s, data)
            #print "S:", s


    #A service check update have just arrived, we UPDATE data info with this
    def manage_service_next_schedule_brok(self, b):
        self.manage_service_check_result_brok(b)


    #In fact, an update of a service is like a check return
    def manage_update_service_status_brok(self, b):
        self.manage_service_check_result_brok(b)
        data = b.data
        #In the status, we've got duplicated item, we must relink thems
        s = self.find_service(data['host_name'], data['service_description'])
        s.check_period = self.get_timeperiod(s.check_period)
        s.notification_period = self.get_timeperiod(s.notification_period)
        s.contacts = self.get_contacts(s.contacts)
        del s.escalations



    def manage_host_check_result_brok(self, b):
        data = b.data
        h = self.find_host(data['host_name'])
        if h != None:
            self.update_element(h, data)
            #print "H:", h


    # this brok should arrive within a second after the host_check_result_brok
    def manage_host_next_schedule_brok(self, b):
        self.manage_host_check_result_brok(b)

    #In fact, an update of a host is like a check return
    def manage_update_host_status_brok(self, b):
        self.manage_host_check_result_brok(b)
        data = b.data
        #In the status, we've got duplicated item, we must relink thems
        h = self.find_host(data['host_name'])
        h.check_period = self.get_timeperiod(h.check_period)
        h.notification_period = self.get_timeperiod(h.notification_period)
        h.contacts = self.get_contacts(h.contacts)
        #Escalations is not use for status_dat
        del h.escalations



    #The contacts must not be duplicated
    def get_contacts(self, cs):
        r = []
        for c in cs:
            if c != None:
                find_c = self.find_contact(c.get_name())
                if find_c != None:
                    r.append(find_c)
                else:
                    print "Error : search for a contact %s that do not exists!" % c.get_name()
        return r


    #The timeperiods must not be duplicated
    def get_timeperiod(self, t):
        if t != None:
            find_t = self.find_timeperiod(t.get_name())
            if find_t != None:
                return find_t
            else:
                print "Error : search for a timeperiod %s that do not exists!" % t.get_name()
        else:
            return None


    def find_host(self, host_name):
        if host_name in self.hostname_lookup_table:
            return self.hosts[self.hostname_lookup_table[host_name]]
        for h in self.hosts.values():
            if h.host_name == host_name:
                return h
        return None


    def find_service(self, host_name, service_description):
        if host_name + service_description in self.servicename_lookup_table:
            return self.services[self.servicename_lookup_table[host_name + service_description]]
        for s in self.services.values():
            if s.host_name == host_name and s.service_description == service_description:
                return s
        return None


    def find_timeperiod(self, timeperiod_name):
        for t in self.timeperiods.values():
            if t.timeperiod_name == timeperiod_name:
                return t
        return None


    def find_contact(self, contact_name):
        for c in self.contacts.values():
            if c.contact_name == contact_name:
                return c
        return None

        
    def update_element(self, e, data):
        #print "........%s........" % type(e)
        for prop in data:
            #if hasattr(e, prop):
            #    print "%-20s\t%s\t->\t%s" % (prop, getattr(e, prop), data[prop])
            #else:
            #    print "%-20s\t%s\t->\t%s" % (prop, "-", data[prop])
            setattr(e, prop, data[prop])


    def main(self):
        last_number_of_objects = 0
        backlog = 5
        size = 8192
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setblocking(0)
        server.bind((self.host, self.port))
        server.listen(backlog)
        input = [server]
        # todo. open self.socket and add it to input

        while True:
            try:
                b = self.q.get(True, .01)  # do not block indefinitely
                self.manage_brok(b)
            except Exception:
                pass
            inputready,outputready,exceptready = select.select(input,[],[], 0)

            for s in inputready:
                if s == server:
                    # handle the server socket
                    client, address = server.accept()
                    input.append(client)
                else:
                    # handle all other sockets
                    data = s.recv(size)
                    if data:
                        response = self.livestatus.handle_request(data)
                        s.send(response)
                    else:
                        s.close()
                        input.remove(s)
            
            if self.number_of_objects > last_number_of_objects:
                # Still in the initialization phase
                # Maybe we should wait until there are no more initial broks
                # before we open the socket
                pass