(function () {
    /** @type {Record<number,Record<string,function[]>>} */
    var LISTENERS = {};
    var py = call_python;

    function Event(type) { this.type = type; this.do_default = true; }
    Event.prototype.preventDefault = function () {
        this.do_default = false;
    }

    function Node(handle) { this.handle = handle; }
    Node.prototype.getAttribute = function(name) { return py("getAttribute", this.handle, name) }
    Node.prototype.appendChild = function(child) { py("appendChild", this.handle, child.handle) }
    Node.prototype.insertBefore = function(toinsert, reference) { py("insertBefore", this.handle, toinsert.handle, reference.handle) }
    Node.prototype.addEventListener = function(type, listener) { 
        if (!LISTENERS[this.handle]) LISTENERS[this.handle] = {};
        var dict = LISTENERS[this.handle];
        if (!dict[type]) dict[type] = [];
        var list = dict[type];
        list.push(listener);
    }
    Node.prototype.dispatchEvent = function(evt) {
        var type = evt.type
        var handle = this.handle;
        var list = (LISTENERS[handle] && LISTENERS[handle][type]) || []
        for (var i=0; i<list.length; i+=1) {
            list[i].call(this, evt)
        }
        return evt.do_default;
    }
    Object.defineProperties(Node.prototype, {
        'innerHTML': {  set: function(s) { py("innerHTML_set", this.handle, s.toString()); }  },
        'children': {  get: function() { return py("children_get", this.handle).map(tonode); }  },
        'onload': {  set: function(fn) { this.addEventListener("load", fn); }}
    })

    function Document() {}
    Document.prototype.querySelectorAll = function(s){ return call_python("querySelectorAll", s).map(tonode) }
    Document.prototype.createElement = function(s){ return tonode(call_python("createElement", s)) }
    Document.prototype.createTextNode = function(s){ return tonode(call_python("createTextNode", s)) }
    Object.defineProperties(Document.prototype, {
        'title': {  get: function() { return py("document_get_title")}, set: function(s) { return py("document_set_title", s.toString()); }  },
        'body': {  get: function() { return tonode(py("document_get_body")) }  },
    })

    function tonode(handle) {
        return new Node(handle)
    }

    function log(x){
        call_python("log", x)
    }
    /** GLOBALS */
    console = { log:log, error:log }
    document = new Document()
    window = { console:console, document:document }
    __dispatch_event = function (handle, type) { return new Node(handle).dispatchEvent(new Event(type)) !== false }
})();