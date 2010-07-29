#!/usr/bin/env python
#Copyright (C) 2009-2010 : 
#    Gabes Jean, naparuba@gmail.com 
#    Gerhard Lausser, Gerhard.Lausser@consol.de
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


#This class is used for poller and reactionner to work.
#The worker is a process launch by theses process and read Message in a Queue
#(self.s) (slave)
#They launch the Check and then send the result in the Queue self.m (master)
#they can die if they do not do anything (param timeout)

from Queue import Empty
from multiprocessing import Process, Queue
from message import Message

import threading
import time, sys

#Worker class
class Worker:
    id = 0#None
    _process = None
    _mortal = None
    _idletime = None
    _timeout = None
    _c = None
    def __init__(self, id, s, returns_queue, processes_by_worker, mortal=True, timeout=300, max_plugins_output_length=8192):
        self.id = self.__class__.id
        self.__class__.id += 1

        self._mortal = mortal
        self._idletime = 0
        self._timeout = timeout
        self.processes_by_worker = processes_by_worker
        self._c = Queue() # Private Control queue for the Worker
        self._process = Process(target=self.work, args=(s, returns_queue, self._c))
        self.returns_queue = returns_queue
        self.max_plugins_output_length = max_plugins_output_length
	#Thread version : not good in cpython :(
        #self._process = threading.Thread(target=self.work, args=(s, returns_queue, self._c))


    def is_mortal(self):
        return self._mortal


    def start(self):
        self._process.start()


    #Kill the backgroup process
    #AND close correctly the queue
    #the queue have a thread, so close it too....
    def terminate(self):
        self._process.terminate()
        self._c.close()
        self._c.join_thread()
        

    def join(self, timeout=None):
        self._process.join(timeout)


    def is_alive(self):
        return self._process.is_alive()


    def is_killable(self):
        return self._mortal and self._idletime > self._timeout


    def add_idletime(self, time):
        self._idletime = self._idletime + time


    def reset_idle(self):
        self._idletime = 0

    
    def send_message(self, msg):
        self._c.put(msg)

        
    #A zombie is immortal, so kill not be kill anymore
    def set_zombie(self):
        self._mortal = False
        

    #Get new checks if less than nb_checks_max
    #If no new checks got and no check in queue,
    #sleep for 1 sec
    #REF: doc/shinken-action-queues.png (3)
    def get_new_checks(self):
        try:
            while(len(self.checks) < self.processes_by_worker):
                #print "I", self.id, "wait for a message"
                msg = self.s.get(block=False)
                if msg is not None:
                    self.checks.append(msg.get_data())
                #print "I", self.id, "I've got a message!"
        except Empty as exp:
            if len(self.checks) == 0:
                self._idletime = self._idletime + 1
                time.sleep(1)


    #Launch checks that are in status
    #REF: doc/shinken-action-queues.png (4)
    def launch_new_checks(self):
        #queue
        for chk in self.checks:
            if chk.status == 'queue':
                self._idletime = 0
                chk.execute()


    #Check the status of checks
    #if done, return message finished :)
    #REF: doc/shinken-action-queues.png (5)
    def manage_finished_checks(self):
        to_del = []
        wait_time = 1
        now = time.time()
        for action in self.checks:
            if action.status == 'launched' and action.last_poll < now - action.wait_time:
                action.check_finished(self.max_plugins_output_length)
                wait_time = min(wait_time, action.wait_time)
                #If action done, we can launch a new one
            if action.status == 'done' or action.status == 'timeout':
                to_del.append(action)
                #We answer to the master
                #msg = Message(id=self.id, type='Result', data=action)
                try:
                    self.returns_queue.append(action)#msg)
                except IOError as exp:
                    print "[%d]Exiting: %s" % (self.id, exp)
                    sys.exit(2)               
        #Little sleep
        self.wait_time = wait_time

        for chk in to_del:
            self.checks.remove(chk)

        #Little seep
        time.sleep(wait_time)
            

    #id = id of the worker
    #s = Global Queue Master->Slave
    #m = Queue Slave->Master
    #return_queue = queue managed by manager
    #c = Control Queue for the worker
    def work(self, s, returns_queue, c):
        timeout = 1.0
        self.checks = []
        self.returns_queue = returns_queue
        self.s = s
        while True:
            begin = time.time()
            msg = None
            cmsg = None

            #REF: doc/shinken-action-queues.png (3)
            self.get_new_checks()
            #REF: doc/shinken-action-queues.png (4)
            self.launch_new_checks()
            #REF: doc/shinken-action-queues.png (5)
            self.manage_finished_checks()

            #Now get order from master
            try:
                cmsg = c.get(block=False)
                if cmsg.get_type() == 'Die':
                    print "[%d]Dad say we are diing..." % self.id
                    break
            except :
                pass
                
            if self._mortal == True and self._idletime > 2 * self._timeout:
                print "[%d]Timeout, Arakiri" % self.id
                #The master must be dead and we are loonely, we must die
                break
            
            timeout -= time.time() - begin
            if timeout < 0:
                timeout = 1.0