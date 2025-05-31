(function () {
    var window = new Function('return this;')();
    /** @type {Record<number,Record<string,function[]>>} */
    var LISTENERS = {};
    var py = call_python;

    window.Event = function Event(type,options) { options=options||{}; this.type = type; this.do_default = true; this.bubbles=options.bubbles==true; this.trusted=false; this.eventPhase=Node.NONE; }
    Event.prototype.preventDefault = function () { this.do_default = false; }
    Event.prototype.stopPropagation = function () { this.bubbles = false; }
    Event.prototype.NONE = 0;
    Event.prototype.CAPTURING_PHASE = 1;
    Event.prototype.AT_TARGET = 2;
    Event.prototype.BUBBLING_PHASE = 3;

    function Node(handle) { this.handle = handle; }
    Node.prototype.getAttribute = function(name) { return py("getAttribute", this.handle, name) }
    Node.prototype.appendChild = function(child) { py("appendChild", this.handle, child.handle) }
    Node.prototype.insertBefore = function(toinsert, reference) { py("insertBefore", this.handle, toinsert.handle, reference.handle) }
    Node.prototype.removeChild = function(toremove) { py("removeChild", this.handle, toremove.handle); return toremove; }
    Node.prototype.addEventListener = function(type, listener) { 
        if (!LISTENERS[this.handle]) LISTENERS[this.handle] = {};
        var dict = LISTENERS[this.handle];
        if (!dict[type]) dict[type] = [];
        var list = dict[type];
        list.push(listener);
    }
    Node.prototype.dispatchEvent = function(event) {
        var type = event.type;
        var handle = this.handle;
        event.eventPhase = Event.AT_TARGET;
        var list = (LISTENERS[handle] && LISTENERS[handle][type]) || []
        for (var i=0; i<list.length; i+=1) {
            list[i].call(this, event)
        }
        if (!event.bubbles) {
            return event.do_default;
        }
        event.eventPhase = Event.BUBBLING_PHASE;
        var parent = this.parent;
        while (parent && event.bubbles) {
            var node = parent;
            parent = parent.parent;
            var listenerTypes = LISTENERS[node.handle];
            if (!listenerTypes) continue;
            var list = listenerTypes[type];
            if (!list) continue;
            for (var i=0; i<list.length; i+=1) {
                list[i].call(node, event);
            }
        }
        return event.do_default;
    }
    Object.defineProperties(Node.prototype, {
        'innerHTML': {  get: function() { return py("innerHTML_get", this.handle); }, set: function(s) { py("innerHTML_set", this.handle, s.toString()); }  },
        'outerHTML': {  get: function() { return py("outerHTML_get", this.handle);}  },
        'children': {  get: function() { return py("children_get", this.handle).map(tonode); }  },
        'onload': {  set: function(fn) { this.addEventListener("load", fn); }},
        'parent': {  get: function() { return tonode(py("parent_get", this.handle)) }  },
    })

    function Document() {}
    Document.prototype.querySelectorAll = function(s){ return call_python("querySelectorAll", s).map(tonode) }
    Document.prototype.createElement = function(s){ return tonode(call_python("createElement", s)) }
    Document.prototype.createTextNode = function(s){ return tonode(call_python("createTextNode", s)) }
    Object.defineProperties(Document.prototype, {
        'title': {  get: function() { return py("document_get_title")}, set: function(s) { return py("document_set_title", s.toString()); }  },
        'body': {  get: function() { return tonode(py("document_get_body")) }  },
    })

    function tonode(handle) { if (handle >= 0) return new Node(handle); return undefined; }
    function log(){ call_python("log", arr(arguments).join(" ")) }
    function arr(arraylike){ var a=[]; for(var i=0;i<arraylike.length;i+=1) a.push(arraylike[i]); return a }
    window.console = { log:log, warn:log, error:log, info:log, debug:log };
    window.document = new Document();
    window.window = window;
    __dispatch_event = function (handle, type) { var event=new Event(type); event.isTrusted=true; event.bubbles=true; return new Node(handle).dispatchEvent(event) !== false }
    __global_node = function (name, handle) { if (typeof window[name] === 'undefined') window[name] = new Node(handle); }
    __global_node_remove = function (name, handle) { if (typeof window[name] !== 'undefined' && window[name] instanceof Node && window[name].handle === handle) delete window[name]; }
})();